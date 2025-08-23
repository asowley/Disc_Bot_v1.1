# Database tools for storing and retrieving ARK server and player information
import datetime
import logging
from datetime import datetime, timedelta, timezone

from pytz import utc, timezone as pytz_timezone
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as ticker
import discord
import os

from tools.EOS import EOS
from tools.connector import db_connector
import aiomysql


async def store_info_to_db(server_number, num_players):
    logging.debug(f"[store_info] Store info {server_number} {num_players}")

    conn = await db_connector()

    # Get the current UTC time and convert it to a Unix timestamp
    epoch_time = int(datetime.now(timezone.utc).timestamp())

    async with conn.cursor() as cursor:
        await cursor.execute("""
            INSERT INTO ark_servers_history (ark_server, players, time)
            VALUES (%s, %s, %s)
        """, (server_number, num_players, epoch_time))
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
    return "No Alias"

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

async def create_history_graph(server_number: str, amount: int):
    try:
        # Calculate the time delta
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=amount)

        # Fetch data from the database
        conn = await db_connector()
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute("""
                SELECT players, time
                FROM ark_servers_history
                WHERE ark_server = %s AND time >= %s
            """, (server_number, int(start_time.timestamp())))
            data = await cursor.fetchall()

        if not data:
            logging.warning(f"No data found for server {server_number} in the last {amount} hours.")
            return None

        # Extract players and time data
        players_data = [record['players'] for record in data]
        time_data = [datetime.fromtimestamp(record['time'], timezone.utc) for record in data]

        # Fetch max players using EOS matchmaking
        eos = EOS()
        _, _, max_players, _ = await eos.matchmaking(server_number)
        if not max_players:
            max_players = 70  # Default to 70 if max_players is not available

        # Create the graph
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.plot(time_data, players_data, label="Players", color="blue", linewidth=2)

        # Set graph title and labels
        ax.set_title(f"Server {server_number} Player History (Last {amount} Hours)", fontsize=14, weight="bold")
        ax.set_xlabel("Time (UTC)", fontsize=12)
        ax.set_ylabel("Players", fontsize=12)

        # Dynamically adjust the x-axis tick intervals based on the time range
        if amount <= 1:  # 1 hour or less
            major_locator = mdates.MinuteLocator(interval=10)  # Major ticks every 10 minutes
            minor_locator = mdates.MinuteLocator(interval=2)   # Minor ticks every 2 minutes
        elif amount <= 6:  # Up to 6 hours
            major_locator = mdates.MinuteLocator(interval=30)  # Major ticks every 30 minutes
            minor_locator = mdates.MinuteLocator(interval=5)   # Minor ticks every 5 minutes
        elif amount <= 12:  # Up to 24 hours
            major_locator = mdates.HourLocator(interval=1)     # Major ticks every 1 hour
            minor_locator = mdates.MinuteLocator(interval=15)  # Minor ticks every 15 minutes
        elif amount <= 24:  # Up to 24 hours
            major_locator = mdates.HourLocator(interval=2)     # Major ticks every 2 hour
            minor_locator = mdates.MinuteLocator(interval=30)  # Minor ticks every 30 minutes
        elif amount <= 48: # Up to 2 days
            major_locator = mdates.HourLocator(interval=4)     # Major ticks every 4 hours
            minor_locator = mdates.HourLocator(interval=1)     # Minor ticks every 1 hour
        elif amount <= 96: # Up to 4 days
            major_locator = mdates.HourLocator(interval=12)    # Major ticks every 12 hours
            minor_locator = mdates.HourLocator(interval=3)     # Minor ticks every 3 hours
        else:  # More than 4 days
            major_locator = mdates.DayLocator(interval=1)     # Major ticks every 1 day
            minor_locator = mdates.HourLocator(interval=4)     # Minor ticks every 4 hours

        # Apply the locators to the x-axis
        ax.xaxis.set_major_locator(major_locator)
        ax.xaxis.set_minor_locator(minor_locator)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))  # Format time as HH:MM

        # Add grid lines
        ax.grid(True, which='major', linestyle='--', linewidth=0.5, alpha=0.7)
        ax.grid(True, which='minor', linestyle=':', linewidth=0.3, alpha=0.5)

        # Format the y-axis
        ax.yaxis.set_major_locator(ticker.MultipleLocator(5))
        ax.yaxis.set_minor_locator(ticker.AutoMinorLocator())
        ax.set_ylim(0, max_players)  # Set the y-axis limit to max players

        # Save the graph to a temporary file
        fname = f"graphs/{server_number}_{int(end_time.timestamp())}.png"
        os.makedirs("graphs", exist_ok=True)
        fig.savefig(fname=fname)
        plt.close(fig)  # Close the figure to release the file

        return fname  # Return the file path instead of the Discord file object

    except Exception as e:
        logging.warning(f"Could not generate graph for server {server_number}: {e}")
        return None
