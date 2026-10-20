
import requests
s = requests.Session()
# Log in first
r_login = s.post("http://127.0.0.1:5000/login", data={"usuario": "GermanMazza", "password": "password123"}) # Wait, password is not password123, we can just use the session cookie from the browser or we can query the database to get the session cookie, but wait, there is no active session cookie in the db.
# Wait, we can bypass login in the test script by temporarily adding a route that doesn require login!

