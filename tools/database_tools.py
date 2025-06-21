import datetime
import logging
from datetime import datetime

from pytz import utc, timezone

from tools.connector import db_connector
import aiomysql


async def store_info_to_db(server_number, players):
    logging.debug(f"[store_info] Store info {server_number} {players}")

    conn = await db_connector()

    local_dt = datetime.now()

    local_tz = timezone('Brazil/East')

    local_dt_with_tz = local_dt.astimezone(local_tz)

    utc_dt = local_dt_with_tz.astimezone(utc)

    epoch_time = utc_dt.timestamp()

    async with conn.cursor() as cursor:
        await cursor.execute("""
            INSERT INTO ark_servers_history (ark_server, players, time)
            VALUES (%s, %s, %s)
        """, (server_number, players, int(epoch_time)))
        await conn.commit()  # Commit the transaction

    return None



async def get_user_alias_and_tribe(puid):

    conn = await db_connector()

    async with conn.cursor(aiomysql.DictCursor) as cursor:
        await cursor.execute("""
            SELECT alias, tribe_alias
            FROM players
            WHERE puid = %s
        """, (puid,))
        result = await cursor.fetchone()

    if result:
        return result['alias'], result['tribe_alias']
    return None, None
