'''
Imports environment variables into the OS.
'''

import re
import os

with open('.env','r') as fp:
    document = fp.read()

    # regex search for key and values in the .env file and assign to variables
    d = re.findall(r'(?P<key>[\w\d_]+)=\"(?P<value>[^\"]*)\"\n?', document)

    # write the key and value pairs to the os environment
    for (key, value) in d:
        os.environ[key] = value