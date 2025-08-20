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
        _, total_players, _, _ = eos.matchmaking(ark_server)
        # info = await eos.info(players)
        # players_display_name = {player['display_name'] for player in info}
        # print(f"Players info for server {ark_server}: {players_display_name}")
        # print("**********************")
        return ark_server, players, total_players
    except Exception as e:
        logging.error(f"[all_servers_monitor.py] Error fetching players for server {ark_server}: {e}")
        return ark_server, []

async def store_players_to_db(conn, ark_server, new_players, timestamp, total_players=None):
    async with conn.cursor() as cursor:
        for puid in new_players:
            await cursor.execute(
                """
                INSERT INTO user_servers (puid, server_alias, timestamp)
                VALUES (%s, %s, %s)
                """,
                (puid, ark_server, timestamp)
            )
        if total_players is not None:
            await cursor.execute(
                """
                INSERT INTO ark_servers_history (ark_server, players, time)
                VALUES (%s, %s, %s)
                """,
                (ark_server, total_players, timestamp)
            )
        await conn.commit()

async def monitor_all_servers(batch_size=50):
    """
    Monitor all servers in batches to prevent WebSocket idle timeouts.
    """
    start_time = time.time()
    eos = EOS()
    conn = await db_connector()
    servers = []

    # Load previous state from file
    state = load_state()

    async with conn.cursor(aiomysql.DictCursor) as cursor:
        await cursor.execute("SELECT ark_server, room_id, tribe FROM ark_servers_new")
        servers = await cursor.fetchall()

    total_servers = len(servers)
    logging.info(f"[all_servers_monitor.py] Starting monitoring for {total_servers} servers in batches of {batch_size}.")

    # Process servers in batches
    for i in range(0, total_servers, batch_size):
        batch = servers[i:i + batch_size]
        logging.info(f"[all_servers_monitor.py] Processing batch {i // batch_size + 1} with {len(batch)} servers.")

        # Prepare tasks for the current batch
        tasks = [
            fetch_players_for_server(eos, server['ark_server'], server['room_id'])
            for server in batch
        ]

        # Run all tasks concurrently for the current batch
        results = await asyncio.gather(*tasks)

        # Store results in the database only for new players
        timestamp = int(time.time())
        for ark_server, players, total_players in results:
            ark_server_str = str(ark_server)
            prev_players = set(state.get(ark_server_str, []))
            current_players = set(players)
            new_players = current_players - prev_players
            if new_players:
                await store_players_to_db(conn, ark_server, new_players, timestamp, total_players)
                logging.info(f"[all_servers_monitor.py] Stored {len(new_players)} new players for server {ark_server} at {timestamp}.")
            # Update state
            state[ark_server_str] = list(current_players)

        # Optional: Add a delay between batches to avoid overwhelming the system
        await asyncio.sleep(5)

    # Save updated state to file
    save_state(state)
    end_time = time.time()
    elapsed = end_time - start_time
    logging.info(f"[all_servers_monitor.py] Monitoring completed in {elapsed:.2f} seconds.")
    

async def main():
    await monitor_all_servers()

if __name__ == "__main__":
    asyncio.run(main())




