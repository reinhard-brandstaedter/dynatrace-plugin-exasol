# -*- coding: utf-8 -*-
from configparser   import ConfigParser
from os             import sep
from os.path        import expanduser, isfile, isdir
from glob           import glob
from platform       import uname

def GetDriverNameFromConfig(odbcIniFile):
    config = ConfigParser()
    config.read(odbcIniFile)
    result = None

    if 'ODBC Data Sources' in config.sections():
        driverName = None
        section = config['ODBC Data Sources']
        for key in section.keys():
            if str(key).startswith('exasolution-'):
                driverName = key
                break
        if driverName and driverName in section and isfile(config[driverName]['DRIVER']):
            result = config[driverName]['DRIVER']
    return result

def GetDriverType():
    files = glob('/usr/lib/*/libodbc.so.*.0.0') + \
            glob('/usr/lib/*/libodbcinst.so.*.0.0') + \
            glob('/usr/lib/*/libodbc.so')

    for item in files:
        if item.endswith('2.0.0'):  return 'uo2214lv2'
        if item.endswith('1.0.0'):  return 'uo2214lv1'
        if item.endswith('.so'):    return 'dd'
    return None

def GetDriverName():
    driverType = GetDriverType()
    if not driverType: 
        return None

    result = None
    odbcIniFile = expanduser("~") + sep + '.odbc.ini'
    if isfile(odbcIniFile):
        result = GetDriverNameFromConfig(odbcIniFile)

    odbcIniFile = '/etc/odbc.ini' 
    if not result and isfile(odbcIniFile):
        result = GetDriverNameFromConfig(odbcIniFile)

    if not result and isdir('/opt/exasol'):
        for item in glob('/opt/exasol/EXASOL_ODBC-*'):
            platformDir = item + sep + 'lib' + sep + str(uname()[0]).lower() + sep + str(uname()[4]).lower()
            if isdir(platformDir):
                driver = platformDir + sep + 'libexaodbc-' + driverType + '.so'
                if isfile(driver):
                    return driver
    return result
