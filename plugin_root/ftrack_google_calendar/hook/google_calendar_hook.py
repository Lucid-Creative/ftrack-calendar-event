'''
ftrack Google Calendar integration hook

Lucid
KBJordahl
9/14/2017

'''

import ftrack_api
import os, sys
import logging, logging.handlers

dir_path = os.path.dirname(os.path.realpath(__file__))
LOG_DIR = os.path.realpath(os.path.join(dir_path,'..','logs','ftrack-google-calendar.log'))
RESOURCE_DIR = os.path.realpath(os.path.join(dir_path,'..','resource'))

# add the resource directory to the mix
try :
    sys.path.index(RESOURCE_DIR)
except:
    sys.path.append(RESOURCE_DIR)
finally:
    from google_calendar_tools import CalendarUpdater
    

ACTION_IDENTIFIER = 'make-project-events'

def setup_logging():
    logger = logging.getLogger("Lucid.GoogleCalendarHook")
    file_handler = logging.handlers.TimedRotatingFileHandler(LOG_DIR,
                                       when="w0",
                                       interval=1,
                                       backupCount=5)

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger

def discover(event):

    actions = {
        'items':[
            {
                'label': "Make Calendar Events",
                'actionIdentifier': ACTION_IDENTIFIER,
                'actionData': {}
            }
        ]
    }

    return actions

def register(session, **kw):
    '''
    This method is called by the ftrack api so it knows which functions to run when asked for a location
    '''

    logger = setup_logging()
    logger.info("Attempting to register Google Calendar Hook")
    
    # Validate that session is an instance of ftrack_api.Session. If not,
    # assume that register is being called from an incompatible API
    # and return without doing anything.
    if not isinstance(session, ftrack_api.Session):
        # Exit to avoid registering this plugin again.
        logger.warn("Register called without valid ftrack_api.Session")
        return

    cal = CalendarUpdater()

    session.event_hub.subscribe(
        'topic=ftrack.update',# and data.entities any (entityType="CalendarEvent" or entityType="MilestoneEvent")',
        cal.handle_ftrack_event
    )
    session.event_hub.subscribe(
        'topic=ftrack.action.discover',
        discover
    )
    session.event_hub.subscribe(
        'topic=ftrack.action.discover and data.actionIdentifier={}'.format(
            ACTION_IDENTIFIER
        ),
        cal.handle_whole_project
    )

    logger.info("Successfully registered")