import configparser
import logging
import aiomysql
import json
import asyncio

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

async def add_ark_server(conn, ark_server, room_id, tribe):
    """
    Adds a new ARK server to the database asynchronously.

    :param conn: The aiomysql connection object.
    :param ark_server: The ARK server identifier.
    :param room_id: The room ID associated with the ARK server.
    :param tribe: The tribe associated with the ARK server.
    """
    logging.debug(f"[connector.py] Adding ARK server {ark_server} with room ID {room_id} and tribe {tribe}")

    async with conn.cursor() as cursor:
        await cursor.execute(
            """
            INSERT INTO ark_servers_new (ark_server, room_id, tribe)
            VALUES (%s, %s, %s)
            """,
            (str(ark_server), int(room_id), str(tribe))
        )
        await conn.commit()
