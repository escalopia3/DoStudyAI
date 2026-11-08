import unittest
from types import SimpleNamespace
from dovideo.business.auth import hash_password, password_matches
from dovideo.business.resources import _filename
from dovideo.errors import ApiError

class DomainTests(unittest.TestCase):
    def test_format_and_url_rejection(self):
        import io
        from dovideo.validation import check_format, InvalidResource
        from dovideo.urlfetch import validate_url
        with self.assertRaises(InvalidResource):
            check_format(io.BytesIO(b'not a PDF'), 'application/pdf')
        with self.assertRaises(InvalidResource):
            validate_url('http://127.0.0.1/private')
    def test_password_hash_is_salted_and_java_compatible_shape(self):
        first = hash_password("correct horse battery staple")
        second = hash_password("correct horse battery staple")
        self.assertNotEqual(first, second)
        self.assertEqual(first.split("$")[0:2], ["pbkdf2", "210000"])
        self.assertTrue(password_matches("correct horse battery staple", first))
        self.assertFalse(password_matches("wrong password", first))

    def test_legacy_plaintext_password_can_be_verified_for_upgrade(self):
        self.assertTrue(password_matches("legacy-password", "legacy-password"))
        self.assertFalse(password_matches("wrong", "legacy-password"))

    def test_upload_filename_removes_client_path(self):
        self.assertEqual(_filename("C:\\fakepath\\lecture.pdf"), "lecture.pdf")
        with self.assertRaises(ApiError):
            _filename("..")
