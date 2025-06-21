import configparser
import logging
import aiomysql

async def db_connector():
    logging.debug(f"[db_connector] Connecting to MySQL")

    # Read the database configuration from the config.ini file
    config = configparser.ConfigParser()
    config.read("config.ini")

    user = config['db']['user']
    password = config['db']['password']
    db_name = config['db']['db_name']
    host = config['db']['host']
    port = int(config['db']['port'])  # Ensure the port is an integer

    # Establish the connection using aiomysql
    try:
        conn = await aiomysql.connect(
            user=user,
            password=password,
            db=db_name,
            host=host,
            port=port
        )

        return conn
    except Exception as e:
        print("Couldnt connect to DB: ", e)