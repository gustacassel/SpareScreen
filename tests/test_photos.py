"""The Photos screen's folder, the photos sent to paired devices, and the scrolling message."""

import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from sparescreen import panel, photos
from sparescreen.config import ConfigStore, clean
from sparescreen.pairing import Pairing
from sparescreen.server import serve


def write_jpeg(path, size=(3000, 2000)):
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (200, 80, 40)).save(path, "JPEG")


class PhotosTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.folder = None
        self.album = photos.Photos(lambda: self.folder)

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_folder_no_photos(self):
        self.assertEqual(self.album.read(), {"count": 0, "version": ""})
        self.folder = str(self.root / "gone")
        self.assertIn("isn't there", self.album.status()["error"])

    def test_finds_images_in_subfolders_only(self):
        for name in ("a.jpg", "b.PNG", "trip/c.webp", "trip/d.gif", "notes.txt", "e.heic", ".hidden.jpg",
                     ".thumbs/f.jpg"):
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            (self.root / name).write_bytes(b"x")
        self.folder = str(self.root)
        listing = self.album.listing()
        self.assertEqual(len(listing["photos"]), 4)
        self.assertEqual(self.album.read()["version"], listing["version"])
        self.assertNotIn(self.tmp.name, json.dumps(listing))  # ids only, never the PC's paths

    def test_new_photos_change_the_version(self):
        (self.root / "a.jpg").write_bytes(b"x")
        self.folder = str(self.root)
        before = self.album.read()["version"]
        (self.root / "b.jpg").write_bytes(b"y")
        self.album.rescan()
        after = self.album.read()
        self.assertEqual(after["count"], 2)
        self.assertNotEqual(after["version"], before)

    def test_big_photos_are_made_screen_sized(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow isn't installed")
        write_jpeg(self.root / "big.jpg")
        self.folder = str(self.root)
        (photo_id,) = self.album.listing()["photos"]
        data, kind = self.album.image(photo_id)
        self.assertEqual(kind, "image/jpeg")
        with Image.open(io.BytesIO(data)) as image:
            self.assertEqual(max(image.size), photos.MAX_SIDE)
        self.assertIsNone(self.album.image("not-a-photo"))

    def test_without_pillow_the_file_goes_as_it_is(self):
        (self.root / "a.png").write_bytes(b"\x89PNG fake")
        self.folder = str(self.root)
        (photo_id,) = self.album.listing()["photos"]
        with mock.patch.dict("sys.modules", {"PIL": None}):
            self.assertEqual(self.album.image(photo_id), (b"\x89PNG fake", "image/png"))


class SettingsTest(unittest.TestCase):
    def test_folder_stays_on_the_pc_and_message_only_from_the_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ConfigStore(Path(tmp) / "config.json")
            store.set_photos_dir(tmp)
            store.set_banner("  Dinner   at 8  ")
            self.assertNotIn("photos_dir", store.read())  # the page never gets the path
            self.assertEqual(store.read()["banner"], "Dinner at 8")
            again = ConfigStore(Path(tmp) / "config.json")
            self.assertEqual((again.photos_dir(), again.read()["banner"]), (tmp, "Dinner at 8"))
            self.assertEqual(clean({"banner": "hacked", "photos_dir": "C:/", "photo_seconds": 20}),
                             {"photo_seconds": 20})  # the phone can't change them
            store.set_banner("x" * 500)
            self.assertEqual(len(store.read()["banner"]), 200)

    def test_pc_window_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.jpg").write_bytes(b"x")
            store = ConfigStore(Path(tmp) / "config.json")
            album = photos.Photos(store.photos_dir)
            p = panel.Panel(config=store, photos=album)
            p.act("photos_set", {"folder": str(Path(tmp) / "missing")})
            self.assertIsNone(store.photos_dir())
            self.assertIn("doesn't exist", p.message)
            p.act("photos_set", {"folder": tmp})
            self.assertEqual(p.display()["count"], 1)
            with mock.patch.object(photos, "pick_folder", return_value=None):
                p.act("photos_pick")  # cancelled: nothing changes
            self.assertEqual(store.photos_dir(), tmp)
            p.act("photos_clear")
            self.assertIsNone(p.display()["folder"])
            p.act("banner_set", {"text": "Hello"})
            self.assertEqual(p.display()["banner"], "Hello")


class EndpointTest(unittest.TestCase):
    def test_photos_need_pairing(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.png").write_bytes(b"\x89PNG fake")
            pairing = Pairing(Path(tmp) / "devices.json", trust_localhost=False)
            config = ConfigStore(Path(tmp) / "config.json")
            album = photos.Photos(lambda: tmp)
            server = serve("127.0.0.1", 0, [config, album], 5, config, pairing)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            base = f"http://127.0.0.1:{server.server_address[1]}"

            def get(path, cookie=None):
                req = urllib.request.Request(base + path)
                if cookie:
                    req.add_header("Cookie", cookie)
                try:
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        return resp.status, resp.read()
                except urllib.error.HTTPError as err:
                    err.close()
                    return err.code, b""

            try:
                (photo_id,) = album.listing()["photos"]
                self.assertEqual(get("/photos")[0], 401)
                self.assertEqual(get("/photo/" + photo_id)[0], 401)
                req = urllib.request.Request(base + "/pair", data=json.dumps({"code": pairing.code}).encode(),
                                             method="POST")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    cookie = resp.headers["Set-Cookie"].split(";", 1)[0]
                status, body = get("/photos", cookie)
                self.assertEqual((status, json.loads(body)["photos"]), (200, [photo_id]))
                with mock.patch.dict("sys.modules", {"PIL": None}):
                    self.assertEqual(get("/photo/" + photo_id, cookie), (200, b"\x89PNG fake"))
                self.assertEqual(get("/photo/../config.json", cookie)[0], 404)
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
