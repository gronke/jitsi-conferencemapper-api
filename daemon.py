#!/usr/bin/env python3
import typing
import sqlite3
import time
import sys
import json
import http.server
from urllib.parse import urlparse, parse_qs

DB_FILE = "/tmp/test.db"
EXPIRE_SECONDS = 60 * 60 * 24 * 3
ID_LENGTH = 5
PORT = 8888
PHONE_NUMBERS = dict(
    DE=["+49123456789"]
)

conn = sqlite3.connect(DB_FILE)


def log(msg: str) -> None:
    print(msg)


class ConferenceMaps:

    conn: sqlite3.Connection

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.__init_table()

    def __init_table(self) -> None:
        c = self.cursor
        c.execute(
            'SELECT name FROM sqlite_master WHERE type = "table" AND name = "conferences"',
        )
        if c.fetchone() is None:
            log("Table 'conferences' initialized")
            c.execute("""
            CREATE TABLE conferences (
              id integer,
              jid text,
              created_time integer 
            )
            """)
            self.conn.commit()

    @property
    def cursor(self) -> sqlite3.Cursor:
        return self.conn.cursor()

    @property
    def current_timestamp(self) -> int:
        return int(time.time())

    def find_by_jid(self, jid: str) -> int:
        c = self.cursor
        c.execute(
            "SELECT id FROM conferences WHERE jid = ?",
            (jid,)
        )
        result = c.fetchone()
        if result is None:
            return self.create_room(jid)
        return int(result[0])

    def create_room(self, jid: str, offset: int=0) -> int:
        new_room_id = self.__generate_room_id(jid, offset)
        if self.find_by_id(new_room_id) is not None:
            return self.create_room(jid, offset+1)
        log(f"Creating room {jid} with ID {new_room_id} (offset {offset})")
        c = self.cursor
        c.execute(
            "INSERT INTO conferences VALUES (?, ?, ?)",
            (new_room_id, jid, self.current_timestamp,)
        )
        self.conn.commit()
        return new_room_id

    def __generate_room_id(self, jid: str, offset: int) -> int:
        h = hash(jid)
        if h < 0:
            h += sys.maxsize
        h += offset
        return int(str(h)[-ID_LENGTH:])


    def find_by_id(self, room_id: int) -> typing.Optional[str]:
        result = self.__lookup_id(room_id)
        if result is None:
            return None
        return str(result[0])

    def __lookup_id(self, room_id: int) -> typing.Tuple[int, str, int]:
        c = self.cursor
        c.execute(
            "SELECT jid FROM conferences WHERE id = ?",
            (int(room_id),)
        )
        return c.fetchone()

    def clean(self) -> None:
        c = self.cursor
        c.execute(
            "DELETE FROM conferences WHERE created_time < ?",
            (self.current_timestamp - EXPIRE_SECONDS,)
        )
        conn.commit()

maps = ConferenceMaps(conn)
maps.clean()


class API(http.server.BaseHTTPRequestHandler):

    def do_GET(self):
        url = urlparse(self.path)

        if url.path == "/phoneNumberList":
            self.__send_json(dict(
                message="Phone numbers available.",
                numbers=PHONE_NUMBERS,
                numbersEnabled=True
            ))
            return
        elif url.path == "/conferenceMapper":
            query = parse_qs(url.query)
            jid = None
            room_id = None
            if ("conference" in query.keys()) and len(query["conference"]):
                jid = str(query["conference"][0])
                try:
                    room_id = maps.find_by_jid(jid)
                except Exception as err:
                    self.__send_json(dict(
                        message="ID allocation failed",
                        conference=jid
                    ), status_code=500)
                    return
                self.__send_json(dict(
                    message="Successfully retrieved conference mapping",
                    id=room_id,
                    conference=jid,
                ))
                return
            elif ("id" in query.keys()) and len(query["id"]):
                try:
                    room_id = int(query["id"][0])
                    if room_id <= 0:
                        raise ValueError()
                except ValueError:
                    self.__send_json(dict(
                        message="Invalid ID"
                    ), status_code=400)
                    return
                jid = maps.find_by_id(room_id)
                if jid is None:
                    self.__send_json(dict(
                        message="Room ID not found"
                    ), status_code=404)
                    return
                else:
                    self.__send_json(dict(
                        message="Successfully retrieved conference mapping",
                        id=room_id,
                        conference=jid,
                    ))
                    return
            else:
                self.__send_json(dict(
                     message="No conference or ID provided."
                ), status_code=400)
                return
            
        self.send_response(404)
        self.end_headers()
        self.wfile.write("Not found".encode("UTF-8"))

    def __send_json(self, data: typing.Dict[str, typing.Any], status_code: int=200) -> None:
        self.send_response(status_code)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("UTF-8"))
        self.wfile.write(b"\n")


if __name__ == "__main__":
    httpd = http.server.HTTPServer(("0.0.0.0", PORT,), API)
    try:
        log(f"Launching HTTP server on port {PORT}")
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()

