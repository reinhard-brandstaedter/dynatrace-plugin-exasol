# -*- coding: utf-8 -*-
import pyodbc
from ExasolDatabaseConnector.ExaOdbcDriver.FindDriver   import GetDriverName
from ExasolDatabaseConnector.ExaDatabaseAbstract        import DatabaseAbstract

class Database(DatabaseAbstract):
    """The Database class easifies the access to your DB instance

    Using the Database class is quite easy:

        #create a new instance
        db = Database(username, password, autocommit = False)

        #do a single query (prepared statement)
        result = db.execute('SELECT USER_NAME FROM SYS.EXA_DBA_USERS WHERE USER_NAME = ?;', username)
        for row in result:
            pprint(row)

        #execute multiple SQL statements:
        db.addToBuffer('CREATE SCHEMA "test123";')
        db.addToBuffer('DROM SCHEMA "test_old";')
        db.executeBuffer()
    
        #close the connection
        db.close()

        Args:
            connectionString (str): Exasol database connection string
            user (str):         username used to login into DB instance
            password (str):     password used to login into DB instance
            autocommit (bool, optional): enables or disables autocommit
    """

    __conn = None
    __connectionTuple = None
    __driver            = ''
    __connectTimeOut    = 30
    __queryTimeOut      = 30
    __defaultSchema     = 'EXA_STATISTICS'

    def __init__(self, connectionString, user, password, autocommit = False):
        self._method = 'ODBC'
        self.__connectionTuple = self.ipFromConnectionString(connectionString)
        self._buffer = []
        if self.__connectionTuple:
            self.__driver = GetDriverName()
            odbcConnectionString = 'Driver=%s;CONNECTTIMEOUT=%i;QUERYTIMEOUT=%i;EXASCHEMA=%s;EXAHOST=%s;EXAUID=%s;EXAPWD=%s;' % (
                self.__driver,
                self.__connectTimeOut,
                self.__queryTimeOut,
                self.__defaultSchema,
                connectionString,
                user,
                password
            )
            self.__conn = pyodbc.connect(odbcConnectionString, autocommit = autocommit)
        else:
            raise RuntimeError('database offline or wrong connection string')


    def execute(self, sqlText, *args):
        """Executes a single SQL statement

            Note:
                This method is to execute a single SQL statement and retrieving the result. If you try
                to execute more than one statement use .addToBuffer() and .executeBuffer() instead.

            Args:
                sqlText:    The SQL statement which should be executed on the DB instance
                *args:      All variables which are necessary to execute a prepared statement; 

            Returns:
                None:       If no result is present
                List:       A list of all result rows
        """
        cursor = self.__conn.cursor()
        result = []
        exe  = cursor.execute(sqlText, *args)
        if exe and cursor.rowcount > 0:
            try:
                fetched = exe.fetchall()
                if fetched:
                    for row in fetched:
                        result.append(row)

            except pyodbc.ProgrammingError as e:
                if not "No results." in str(e):
                    raise pyodbc.ProgrammingError(e)

            return result
        return None


    def close(self):
        """Closes the connection to the database instance
            
            Args:
                None

            Returns:
                None
        """
        self.__conn.close()


    def executeBuffer(self):
        """Executes the content of the internal SQL buffer on the DB instance

            Args:
                None

            Return:
                A list with all results for each line
        """
        results = []
        for sql in self._buffer:
            results.append(self.execute(sql))
        self.cleanBuffer()
        return results

