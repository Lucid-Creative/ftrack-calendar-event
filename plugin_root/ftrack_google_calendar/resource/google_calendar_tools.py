'''

Google Calendar Toolset

KBjordahl
Lucid

092517
'''


import httplib2
import simplejson as json
import os
import re
import logging, logging.handlers
from apiclient import discovery, errors
from oauth2client.service_account import ServiceAccountCredentials
import ftrack_api
import arrow
import colour

class CalendarUpdater(object):
    '''
    The calendar updater initializes a connection to a Google Service Account
    and handles updating the events of the users in a single Google Apps domain
    based on events in ftrack.

    It also generates a single unified "projects" calendar on the service account.

    This relies on having a google service account auth file in JSON format stored 
    into the env var GOOGLE_SERVICE_AUTH

    This also relies on the standard FTRACK_SERVER_URL, FTRACK_API_KEY and 
    FTRACK_API_USER vars

    '''

    # this is relative to the root of the plugin
    LOG_DIR = "logs"
    LOG_LEVEL = logging.DEBUG

    def __init__(self):

        self.logger = self.setup_logging(__name__)
        
        self.logger.info("Initializing Google API Credentials")

        # create the calendar api service
        try:
            credentials = ServiceAccountCredentials.from_json_keyfile_dict(
                json.loads(os.environ['GOOGLE_SERVICE_AUTH'].replace("'","\"")),
                scopes = 'https://www.googleapis.com/auth/calendar'
            )
            self.calendar_service = discovery.build('calendar', 'v3', credentials=credentials)
            self.logger.info("Successfully connected to Google.")
        except Exception as e:
            self.logger.error("Ran into some trouble connecting to Google", exc_info=True)
            raise e
        
    def handle_ftrack_event(self, event):
        '''
        Handles the processing and routing of an ftrack event

        '''
        self.logger = self.setup_logging(__name__)
        self.logger.info("Received new event with %d entities", len(event['data']['entities']))
        # an event could contain multiple updates
        for e in event['data']['entities']:
            # first, filter out all non-essential events:
            if e['entityType'] not in ['calendarevent', 'task']:
                # this is not an event we want
                self.logger.info("Passing on entity")
                continue
            else:
                self.session = ftrack_api.Session()
                # transform the data from the event into an api object
                entity = self.session.get(
                    self.get_entity_type(e), 
                    e['entityId']
                )
    
                # now that we're sure that we have an event we want, do the thing
                self.logger.debug("Putting %s %s on Calendar", entity.entity_type, entity['name'])
                self.put_on_calendar(entity)

    def handle_whole_project(self, event):
        '''
        Takes the context it's passed and does all the calendarable children
        '''
        self.logger.info("Received Make Calendar Event action call!")
        self.session = ftrack_api.Session()

        id_match = " or ".join([
            "id='{}'".format(entity['entityId']) 
            for entity in event['data']['selection']])

        # q = self.session.query(
        #     "TypedContext where link any ({})".format(id_match))

        # for entity in q:
        #     self.put_on_calendar(entity)
        
        # if the project is selected, it will match for the calendar event
        q_calendar_event = self.session.query(
            "CalendarEvent where project has ({})".format(id_match))
        q_milestone = self.session.query(
            "Milestone where ancestors any ({})".format(id_match))
        q_task = self.session.query(
            "Task where ancestors any ({})".format(id_match))

        self.logger.debug("Q= Task where link any (%s)",id_match)
        
        try:
            for entity in q_calendar_event:
                self.logger.debug("Putting CalEvent %s on Calendar:", entity['name'])
                self.put_on_calendar(entity)
        except Exception as e:
            self.logger.error("Error updating CalendarEvents", exc_info=True)
        
        try:
            for entity in q_milestone:
                self.logger.debug("Putting Milestone %s on Calendar:", entity['name'])
                self.put_on_calendar(entity)
        except Exception as e:
            self.logger.error("Error updating Milestones", exc_info=True)
        
        try:
            for entity in q_task:
                self.logger.debug("Putting Task %s on Calendar:", entity['name'])
                self.put_on_calendar(entity)
        except Exception as e:
            self.logger.error("Error updating Tasks", exc_info=True)
   
            
        
    def put_on_calendar(self, entity):
        self.session = ftrack_api.Session()
        calendar_color = self.get_calendar_event_color(entity['project'])
        self.update_team_calendar(entity, color=calendar_color)

        self.session.commit()

    def update_team_calendar(self, entity, color=None):
        '''
        This does the dirty work of adding or updating a calendar item in google based on the ftrack entity

        The ftrack entity will get "team_calendar_id" metadata to identify it for future updates
        '''
        try:
            event = self.entity_to_event(entity, color)
        except TypeError as e:
            self.logger.error("Could not generate event from this entity: %s (%s|%s)",
                entity['name'],
                entity.entity_type,
                entity['id'],
                exc_info=True)

        calendar = self.ensure_calendar("ftrack")

        # determine from google if we have the event already
        try:
            event_search = self.calendar_service.events().list(
                calendarId = calendar,
                privateExtendedProperty= 
                ["ftrack_id={}".format(entity['id']),
                "ftrack_type={}".format(entity.entity_type)]
            ).execute()

            num_results = len(event_search['items'])
            if num_results > 1:
                raise NotImplementedError("Cannot determine which Google Calendar Event to use, too many matches")
            elif num_results == 1:
                event_id = event_search['items'][0]['id']
            elif num_results == 0:
                event_id = None
        
        except Exception as e:
            self.logger.error("Couldn't disabiguate existing calendar items!", exc_info=True)
            return False

        if event_id is None:
            # we haven't yet created an event for this
            event_response = self.calendar_service.events().insert(
                calendarId=calendar,
                body = event,
                sendNotifications = False
            ).execute()
            
            # take this out until ftrack adds metadata to CalendarEvents
            # entity['metadata']['team_calendar_id'] = event_response['id']
        
        else:
            # we should update, since the event has already been created
            event_response = self.calendar_service.events().update(
                calendarId=calendar,
                eventId=event_id,
                body = event,
                sendNotifications = False
            ).execute()
        
        
    def entity_to_event(self, entity, color):
        self.logger.info("Creating entity for %s %s", entity['name'], entity.entity_type)

        # initialize the number of people invited
        invited_users = []

        # avoid any entities that don't have a project 
        # (appears to only be leave type CalendarEvents)
        if entity['project'] is not None:
            summary = "{} | {}".format(
                entity['name'],
                entity['project']['full_name']
                )  

        # set up some things if its a task        
        if entity.entity_type == "Task":
            #if it also doesn't have an end date, then bail on this
            if entity['start_date'] is None and entity['end_date'] is None:
                raise TypeError("Must have a start or end date!")

            if entity['start_date'] is None:
                # milestones don't have a start date, so for google calendar
                # we make them start on the end date and set up the 
                start_dt = str(entity['end_date'])
                end_arrow = entity['end_date'].shift(minutes=+30)
                end_dt = str(end_arrow)

            elif entity['end_date'] is None:
                # not sure why theres no end?
                start_dt = str(entity['start_date'])
                end_arrow = entity['start_date'].shift(minutes=+30)
                end_dt = str(end_arrow)

            else:
                start_dt = str(entity['start_date'])
                end_dt = str(entity['end_date'])
            
            # create the dates for the event format
            start = {
                'dateTime': start_dt,
                'timeZone': 'UTC',
            }
            end = {
                'dateTime': end_dt,
                'timeZone': 'UTC',
            }

            invited_users = [u['resource'] for u in entity['assignments']]


        # slightly different mappings for CalendarEvents 
        elif entity.entity_type == "CalendarEvent":
            self.logger.debug("Using CalendarEvent mode")
            start = { 'date': entity['start'].format("YYYY-MM-DD") }
            end = { 'date': entity['end'].format("YYYY-MM-DD")}
            
            if entity['leave'] is True:
                # google color id 8 is grey, which we'll use for leave
                color = "8" 
                summary = "LEAVE: {} | {}".format(
                    ", ".join([u['resource']['first_name'] 
                        for u in entity['calendar_event_resources']]),
                    entity['name']
                )
            
            invited_users = [u['resource'] for u in entity['calendar_event_resources']]

        # make an attendee list
        if len(invited_users) > 0:
            attendees = [{'email': u['email']} for u in invited_users]
        else:
            attendees = []

        event = {
            'summary': summary,
            'location': '',
            'description': entity.get('description'),
            'start': start,
            'end': end,
            'reminders': {
                'useDefault': False,
            },
            'attendees': attendees,
            'extendedProperties': {
                'private': {
                    'ftrack_id': entity['id'],
                    'ftrack_type': entity.entity_type
                }
            }
        }

        if color is not None:
            event['colorId'] = color

        self.logger.debug("Finished constructing event for entity: \n%s", json.dumps(event))

        return event


    def ensure_calendar(self, calendar_name):
        '''
        ensures that the named calendar exists, and is shared with the domain
        '''

        self.logger.info("Ensuring that calendar'%s' exists", calendar_name)
        #iterate through all the calendars
        page_token = None
        while True:
            calendar_list = self.calendar_service.calendarList().list(pageToken=page_token).execute()
            for calendar in calendar_list['items']:
                if calendar['summary'] == calendar_name:
                    self.logger.info("Found existing calendar %s (%s)", calendar['summary'], calendar['id'])
                    # ensure we've shared the calendar
                    self.share_calendar(calendar['id'])
                    return calendar['id']
            page_token = calendar_list.get('nextPageToken')
            if not page_token:
                break

        # if we got here, the calendar doesn't exist. make it

        self.logger.warning("Couldn't find calendar '%s', creating instead", calendar_name)

        try:    
            created_calendar = self.calendar_service.calendars().insert(
                body={
                    'summary': calendar_name,
                    'timeZone': 'America/Los_Angeles'
                    }
            ).execute()
            self.logger.info("Creation successful! id: %s", created_calendar['id'],)
        except Exception as e:
            self.logger.error("Failed to create calendar", exc_info=True)
        
        else:
            try:
                # add the calendar to the list of the service account so we can find it later
                updated_calendar_list = self.calendar_service.calendarList().insert(
                    body={
                        'id':created_calendar['id']
                    }
                ).execute()
                self.logger.info("Added to service account calendar list")

                self.share_calendar(created_calendar['id'])
            except Exception as e:
                self.logger.error("Failed to configure calendar (id: %s) -- it may be in a bad state!!!",
                    exc_info=True)

        return created_calendar['id']

    def share_calendar(self, calendar_id):
        # share with lucid's calendar share group
        try:
            acl = self.calendar_service.acl().insert(
                calendarId=calendar_id,
                body={
                    'scope': {
                        'type': 'group',
                        'value': 'internal-calendar-share@lucidsf.com'
                    },
                    'role': 'owner'
                }
            ).execute()

            return True
        except Exception as e:
            self.logger.error("Couldn't Share calendar id %s", calendar_id, exc_info=True)
    
    def get_calendar_event_color(self, project):
        '''
        ensures that the color for the project is in google, and returns the color instance
        '''
        try:
            ftrack_colour = colour.Color(project['color'])
        except Exception as e:
            self.logger.error("Can't get project color -- maybe a non-project event?", exc_info=True)
            return None
        try:
            google_colors = self.calendar_service.colors().get().execute()
        except Exception as e:
            self.logger.error("Couldn't get colors list. Bailing on color.", exc_info=True)
            return None

        # arbitrarily high hue dif to start
        best_score = 100
        best_color = None

        try:
            for color_id, color in google_colors['event'].items():
                google_colour = colour.Color(color['background'])

                r = abs(google_colour.red - ftrack_colour.red)
                g = abs(google_colour.green - ftrack_colour.green)
                b = abs(google_colour.blue - ftrack_colour.blue)
                
                this_score = r+g+b


                if this_score<best_score:
                    best_color = color_id
                    best_score = this_score
                
            self.logger.info("Determined best color to be id: %s (%s)", 
                best_color, 
                google_colors['event'][color_id])

            return best_color

        except Exception as e:
            self.logger.error("Issue with picking color, skipping on.", exc_info=True)

    def setup_logging(self, name):
        logger = logging.getLogger(name)

        dir_path = os.path.dirname(os.path.realpath(__file__))
        log_file = os.path.join(
            dir_path,
            "..",
            os.path.normpath(self.LOG_DIR),
            'ftrack-google-calendar.log'
        )

            # protect file logging for heroku
        if not os.path.isdir("/app/.heroku"):
            file_handler = logging.handlers.TimedRotatingFileHandler(LOG_DIR,
                                            when="w0",
                                            interval=1,
                                            backupCount=5)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

        else:
            logging.basicConfig(level=self.LOG_LEVEL)
            
        logger.setLevel(self.LOG_LEVEL)
        return logger

    def get_entity_type(self, entity):
        '''Return translated entity type tht can be used with API.'''
        entity_type = entity.get('entityType')
        entity_id = entity.get('entityId')
        object_typeid = entity.get('objectTypeId')

        for schema in self.session.schemas:
            alias_for = schema.get('alias_for')

            if (
                alias_for and isinstance(alias_for, dict) and
                alias_for['id'].lower() == entity_type and
                object_typeid == alias_for.get('classifiers', {}).get('object_typeid')
            ):
                return schema['id']

        for schema in self.session.schemas:
            alias_for = schema.get('alias_for')

            if (
                alias_for and isinstance(alias_for, basestring) and
                alias_for.lower() == entity_type
            ):
                return schema['id']

        for schema in self.session.schemas:
            alias_for = schema.get('alias_for')

            if schema['id'].lower() == entity_type:
                    return schema['id']

        raise ValueError('Unable to translate entity type.')

