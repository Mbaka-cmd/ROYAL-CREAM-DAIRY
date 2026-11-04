from django.test import TestCase


class SmokeTests(TestCase):
    def test_home_page_loads(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Royal Cream Dairy")