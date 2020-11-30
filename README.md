# A Remote Plugin to Monitor Exasol Databases
This is a Active Gate remote plugin that allows the monitoring of the [Exasol Analytics Database](https://www.exasol.com/). It solely uses the statistics and metadata tables provided by Exasol to gather information.

## Dependencies
This plugin depends on the [Exasol Python Database Connector](https://github.com/florian-reck/ExasolDatabaseConnector) which in turn depends on the [unixodbc](http://www.unixodbc.org/) library. As the unixodbc library is a native library it must be present on your Active Gate system.
Note: I have only developed and tested this on Linux Systems.

## What's included
Currenlty I've implemented a few metrics I thought useful by fetching them from various exasol [statistical system tables](https://docs.exasol.com/sql_references/metadata/statistical_system_table.htm#Statistical_System_Tables). This approach is generic enough to add more information or eventually also implement more complex processing of this data (e.g. to implement best practices for health notification). One such best practice has been added for the swap metric (swapping is never ideal for In-Memory DBs :-)

Also included is a scraping of the events table so that Dynatrace can process information about certain DB events (like STARTUP, SHUTDOWN, BACKUP started/stopped, ...)

The availability is also reported based on the successful connection from the AG to the database.

### Screenshots

![availability](./images/availability.png =100x20)
![availability](./images/sql_executions.png =100x20)
![availability](./images/db_events.png =100x20)
![availability](./images/db_sizes.png =100x20)
![availability](./images/keycharts.png =100x20)
![availability](./images/technology.png =100x20)
