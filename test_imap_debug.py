#!/usr/bin/env python3
"""Direct IMAP test script to debug connection issues."""

import asyncio
import aioimaplib

async def test_163_imap():
    email_addr = "wyz9527110@163.com"
    password = "GSxEMysFeci5jyrF"

    print(f"Connecting to imap.163.com:993...")

    client = aioimaplib.IMAP4_SSL(host="imap.163.com", port=993, timeout=30)
    await client.wait_hello_from_server()
    print("✓ Connected to server")

    # Login
    result, data = await client.login(email_addr, password)
    print(f"Login result: {result}")
    print(f"Login data: {data}")

    if result != "OK":
        print("✗ Login failed!")
        return

    print("✓ Logged in successfully!")

    # List folders - try different approaches
    print("\n--- Testing LIST command ---")

    # Method 1: list with empty args
    try:
        result, data = await client.list()
        print(f"list() result: {result}, data: {data}")
    except Exception as e:
        print(f"list() error: {e}")

    # Method 2: list with reference and pattern
    try:
        result, data = await client.list("", "*")
        print(f"list('', '*') result: {result}")
        for item in data:
            print(f"  Folder: {item}")
    except Exception as e:
        print(f"list('', '*') error: {e}")

    # Method 3: list with reference
    try:
        result, data = await client.list("", "INBOX")
        print(f"list('', 'INBOX') result: {result}, data: {data}")
    except Exception as e:
        print(f"list('', 'INBOX') error: {e}")

    # Select INBOX
    print("\n--- Testing SELECT command ---")
    try:
        result, data = await client.select("INBOX")
        print(f"select('INBOX') result: {result}")
        print(f"select data: {data}")
    except Exception as e:
        print(f"select error: {e}")

    # Search for messages
    print("\n--- Testing SEARCH command ---")
    try:
        result, data = await client.search("ALL")
        print(f"search('ALL') result: {result}")
        print(f"search data: {data}")
        if data[0]:
            uids = data[0].decode().split()
            print(f"Found {len(uids)} messages")
            if uids:
                print(f"First 5 UIDs: {uids[:5]}")
    except Exception as e:
        print(f"search error: {e}")

    # Logout
    await client.logout()
    print("\n✓ Disconnected")

if __name__ == "__main__":
    asyncio.run(test_163_imap())
