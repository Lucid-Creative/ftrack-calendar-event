import ftrack_api
import os, sys
import setup
import logging

dir_path = os.path.dirname(os.path.realpath(__file__))
plugin_path = os.path.realpath(os.path.join(dir_path,'..','plugin_root'))

os.environ['FTRACK_EVENT_PLUGIN_PATH'] = plugin_path

def main():
    
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO)

    session = ftrack_api.Session()

    session.event_hub.wait()

if __name__ == '__main__':
    main()
