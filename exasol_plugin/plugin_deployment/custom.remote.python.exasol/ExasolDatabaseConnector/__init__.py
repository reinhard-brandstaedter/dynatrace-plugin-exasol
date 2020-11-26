# -*- coding: utf-8 -*-
import ExasolDatabaseConnector.ExaWebSockets
from ExasolDatabaseConnector.ExaOdbcDriver.FindDriver   import GetDriverName

driverName = GetDriverName()

if driverName and driverName != '':
    class Database(ExasolDatabaseConnector.ExaOdbcDriver.Database):
        def __init__(self, connectionString, user, password, autocommit = False):
            super().__init__(connectionString, user, password, autocommit)

else:
    class Database(ExasolDatabaseConnector.ExaWebSockets.Database):
        def __init__(self, connectionString, user, password, autocommit = False):
            super().__init__(connectionString, user, password, autocommit)


