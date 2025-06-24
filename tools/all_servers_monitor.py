import asyncio
import logging
from tools.EOS import EOS
from tools.connector import db_connector
import aiomysql
import time
import json
import os

STATE_FILE = "server_player_state.json"

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

async def fetch_players_for_server(eos, ark_server, room_id):
    try:
        players = await eos.players(ark_server, room_id)
        logging.info(f"[all_servers_monitor.py] Server {ark_server}: {len(players)} players")
        return ark_server, players
    except Exception as e:
        logging.error(f"[all_servers_monitor.py] Error fetching players for server {ark_server}: {e}")
        return ark_server, []

async def store_players_to_db(conn, ark_server, new_players, timestamp):
    async with conn.cursor() as cursor:
        for puid in new_players:
            await cursor.execute(
                """
                INSERT INTO user_servers (puid, server_alias, timestamp)
                VALUES (%s, %s, %s)
                """,
                (puid, ark_server, timestamp)
            )
        await conn.commit()

async def monitor_all_servers():
    start_time = time.time()
    eos = EOS()
    conn = await db_connector()
    servers = []

    # Load previous state from file
    state = load_state()

    async with conn.cursor(aiomysql.DictCursor) as cursor:
        await cursor.execute("SELECT ark_server, room_id, tribe FROM ark_servers")
        servers = await cursor.fetchall()

    # Prepare tasks for all servers (room_id of 0 is allowed)
    tasks = [
        fetch_players_for_server(eos, server['ark_server'], server['room_id'])
        for server in servers
    ]

    # Run all tasks concurrently
    results = await asyncio.gather(*tasks)

    # Store results in the database only for new players
    timestamp = int(time.time())
    for ark_server, players in results:
        ark_server_str = str(ark_server)
        prev_players = set(state.get(ark_server_str, []))
        current_players = set(players)
        new_players = current_players - prev_players
        if new_players:
            await store_players_to_db(conn, ark_server, new_players, timestamp)
            logging.info(f"[all_servers_monitor.py] Stored {len(new_players)} new players for server {ark_server} at {timestamp}.")
        # Update state
        state[ark_server_str] = list(current_players)

    # Save updated state to file
    save_state(state)
    end_time = time.time()
    elapsed = end_time - start_time
    print(f"[all_servers_monitor.py] Monitoring completed in {elapsed:.2f} seconds.")


