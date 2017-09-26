'''
tests for google_calendar_tools.py

KBjordahl
Lucid
092517

'''

import pytest
import sys, os
import setup

sys.path.append("plugin_root")
from ftrack_google_calendar.resource.google_calendar_tools import CalendarUpdater

def test_setup_calendar_and_share():
    gcal = CalendarUpdater()
    result = gcal.ensure_calendar("ftrack_dummy_test")
 
    assert result == "84hac01kjjaajmuoh1e37d3nj0@group.calendar.google.com"


def test_colors():
    gcal = CalendarUpdater()
    test_project = {'color': "#00BCD4"}
    result = gcal.get_calendar_event_color(test_project)
    assert result == '7'


    
