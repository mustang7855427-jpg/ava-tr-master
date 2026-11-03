import logging
import binascii
import time
import redis
from bitstring import BitArray, ConstBitStream
import protocol
import common
import const


class Client():
    def __init__(self, server):
        self.server = server
        self.uid = None
        self.connection_id = None
        self.encrypted = False
        self.compressed = False
        self.checksummed = False
        self.room = ""
        self.position = (0, 0)
        self.dimension = 4
        self.state = 0
        self.action_tag = ""

    def handle(self, connection, address):
        self.address = address
        self.connection = connection
        logging.debug(f"Połączenie od {address[0]}")
        buffer = ConstBitStream()
        while True:
            try:
                data = connection.recv(1024)
            except OSError:
                break
            if not data:
                break
            disconnect = False
            logging.debug(
                "Odebrano %d bajtów od klienta gry %s",
                len(data), address[0])
            data = buffer + ConstBitStream(data)
            buffer = ConstBitStream()
            if data.hex == "3c706f6c6963792d66696c652d726571756573742f3e00":
                send_data = BitArray(const.XML)
                send_data.append("0x00")
                connection.send(send_data.bytes)
                continue
            while len(data) - data.pos > 32:
                try:
                    length = data.read(32).int
                    if (len(data) - data.pos) / 8 < length:
                        data.pos = 0
                        break
                    final_data = protocol.processFrame(
                        data.read(length * 8), True)
                except Exception:
                    logging.exception(
                        "Nie można odczytać pakietu klienta gry %s",
                        address[0])
                    disconnect = True
                    break
                if final_data:
                    try:
                        self.server.process_data(final_data, self)
                    except Exception:
                        logging.exception(
                            "Błąd podczas przetwarzania danych klienta gry")
                        disconnect = True
                        break
            if disconnect:
                try:
                    connection.shutdown(2)
                except OSError:
                    pass
                break
            if len(data) - data.pos > 0:
                buffer = data.read(len(data) - data.pos)
        self._close_connection()

    def send(self, msg, type_=34):
        data = BitArray(f"int:8={type_}")
        data.append(protocol.encodeArray(msg))
        data.insert(self._make_header(data), 0)
        try:
            self.connection.sendall(data.bytes)
        except (BrokenPipeError, OSError):
            self.connection.close()

    def _make_header(self, msg):
        buf = BitArray()
        header_length = 1
        if self.checksummed:
            header_length += 4
        buf.append(f"int:32={len(msg.hex)//2+header_length}")
        buf.append(f"int:8={self._header_to_byte()}")
        if self.checksummed:
            buf.append(f"uint:32={binascii.crc32(msg.bytes) % (1<<32)}")
        return buf

    def _header_to_byte(self):
        mask = 0
        if self.encrypted:
            mask |= (1 << 1)
        if self.compressed:
            mask |= (1 << 2)
        if self.checksummed:
            mask |= (1 << 3)
        return mask

    def _close_connection(self):
        self.connection.close()
        logging.debug(f"Połączenie z {self.address[0]} zostało zamknięte")
        if self.uid:
            if self.room:
                prefix = common.get_prefix(self.room)
                for client in self.server.online.copy():
                    if client.room != self.room:
                        continue
                    client.send([prefix+".r.lv", {"uid": self.uid}])
                    client.send([self.room, self.uid], type_=17)
            if self.uid in self.server.inv:
                self.server.inv[self.uid].expire = time.time()+30
            if self in self.server.online:
                self.server.online.remove(self)
            if self.connection_id:
                try:
                    self.server.redis.eval(
                        "if redis.call('GET', KEYS[1]) == ARGV[1] then "
                        "redis.call('DEL', KEYS[1]); "
                        "redis.call('SREM', KEYS[2], ARGV[2]); "
                        "return 1 end return 0",
                        2, f"game:connection:{self.uid}", "game:online",
                        self.connection_id, self.uid)
                except redis.RedisError:
                    logging.exception(
                        "Nie udało się zaktualizować listy online dla UID %s",
                        self.uid)
        del self
