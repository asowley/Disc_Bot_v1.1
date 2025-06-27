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

async def get_user_alias(puid, conn=None):
    """
    Returns the alias for a given puid, or 'Unknown' if not found.
    Accepts an optional conn for efficiency in batch operations.
    """
    close_conn = False
    if conn is None:
        conn = await db_connector()
        close_conn = True

    async with conn.cursor(aiomysql.DictCursor) as cursor:
        await cursor.execute("""
            SELECT alias
            FROM players
            WHERE puid = %s
        """, (puid,))
        result = await cursor.fetchone()

    if close_conn:
        conn.close()

    if result and result['alias']:
        return result['alias']
    return "Unknown"

async def get_user_tribe_and_most_joined_server(puid, conn=None):
    """
    Returns (tribe, server_alias) for the server the user has joined most.
    If tribe is unknown, tribe will be None or "Unknown".
    """
    close_conn = False
    if conn is None:
        conn = await db_connector()
        close_conn = True
    async with conn.cursor(aiomysql.DictCursor) as cursor:
        # Find the server the user has joined most
        await cursor.execute(
            """
            SELECT us.server_alias, COUNT(*) AS join_count
            FROM user_servers us
            WHERE us.puid = %s
            GROUP BY us.server_alias
            ORDER BY join_count DESC
            LIMIT 1
            """,
            (puid,)
        )
        row = await cursor.fetchone()
        if row:
            server_alias = row['server_alias']
            # Now get the tribe for that server
            await cursor.execute(
                "SELECT tribe FROM ark_servers_new WHERE ark_server = %s",
                (server_alias,)
            )
            tribe_row = await cursor.fetchone()
            tribe = tribe_row['tribe'] if tribe_row and tribe_row['tribe'] else "Unknown"
            return tribe, server_alias
    if close_conn:
        conn.close()
    return "Unknown", None
