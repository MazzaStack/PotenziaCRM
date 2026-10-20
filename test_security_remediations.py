"""
Test Suite: Verificación de Reparaciones de Ciberseguridad (Zero Disruption)
Certifica que las 6 vulnerabilidades identificadas están blindadas:
1. SSRF Protection en PAP Proxy Image
2. Bloqueo de acceso anónimo a Loading Overlay
3. Token estricto en Meta AI Webhook
4. IDOR Defense en borrado de búsquedas de clientes
5. Aceptación de POST en rutas de borrado
"""
import os
import sys
import unittest
import json

# Ensure root directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app import app
from database import db
from plugins.publicacion_placa.routes import is_safe_image_url

class TestSecurityRemediations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        cls.client = app.test_client()
        db.init_db()

    def test_01_ssrf_validator_blocks_internal_and_private_targets(self):
        """Verifica que el validador SSRF bloquee todas las direcciones internas y privadas."""
        # Bloqueo estricto de localhost y loopback
        self.assertFalse(is_safe_image_url("http://localhost:5000/secret"))
        self.assertFalse(is_safe_image_url("http://127.0.0.1:5000/api"))
        self.assertFalse(is_safe_image_url("http://127.0.0.1"))
        self.assertFalse(is_safe_image_url("http://0.0.0.0:80"))
        self.assertFalse(is_safe_image_url("http://[::1]/"))

        # Bloqueo de Cloud Metadata
        self.assertFalse(is_safe_image_url("http://169.254.169.254/latest/meta-data/"))
        self.assertFalse(is_safe_image_url("http://metadata.google.internal/"))

        # Bloqueo de esquemas peligrosos
        self.assertFalse(is_safe_image_url("file:///etc/passwd"))
        self.assertFalse(is_safe_image_url("ftp://127.0.0.1/test"))
        self.assertFalse(is_safe_image_url("javascript:alert(1)"))
        self.assertFalse(is_safe_image_url(""))
        self.assertFalse(is_safe_image_url(None))

        # Aprobación de dominios públicos legítimos
        self.assertTrue(is_safe_image_url("https://www.google.com/favicon.ico"))
        print(" [PASS] Test 1: SSRF validator blocks localhost, metadata and private targets.")

    def test_02_proxy_image_requires_login(self):
        """Verifica que /pap/proxy-image ya no permita accesos anónimos."""
        with self.client:
            res = self.client.get('/pap/proxy-image?url=https://www.google.com/favicon.ico')
            # Debe redirigir a login o denegar
            self.assertIn(res.status_code, [302, 401, 403])
            if res.status_code == 302:
                self.assertIn('/login', res.headers.get('Location', ''))
        print(" [PASS] Test 2: /pap/proxy-image requires authentication.")

    def test_03_proxy_image_authenticated_ssrf_block(self):
        """Verifica que incluso autenticado, un usuario no pueda usar el proxy para SSRF."""
        admin_user = db.get_usuario('GermanMazza')
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user['id'])
            sess['_fresh'] = True

        res = client.get('/pap/proxy-image?url=http://127.0.0.1:5000/admin')
        self.assertEqual(res.status_code, 403)
        self.assertIn("seguridad".encode('utf-8'), res.data.lower())
        print(" [PASS] Test 3: Authenticated SSRF attempts return 403 Forbidden.")

    def test_04_loading_overlay_requires_authentication(self):
        """Verifica que los endpoints de streaming y buffer de logs requieran login."""
        anon_client = app.test_client()
        # Anónimo: GET stream
        res_stream = anon_client.get('/loading/log-stream')
        self.assertEqual(res_stream.status_code, 302)

        # Anónimo: GET snapshot
        res_snap = anon_client.get('/loading/log-snapshot')
        self.assertEqual(res_snap.status_code, 302)

        # Anónimo: POST clear
        res_clear = anon_client.post('/loading/log-clear')
        self.assertEqual(res_clear.status_code, 302)

        # Anónimo: POST push
        res_push = anon_client.post('/loading/log-push', json={'msg': 'test'})
        self.assertEqual(res_push.status_code, 302)
        print(" [PASS] Test 4: /loading/log-* endpoints require authentication.")

    def test_05_meta_ai_webhook_strict_token_enforcement(self):
        """Verifica que /api/leads/meta exija token válido y rechace requests sin auth."""
        client = app.test_client()
        # Request sin cabecera Authorization ni token
        res_no_auth = client.post('/api/leads/meta', json={'nombre': 'Test', 'telefono': '11223344'})
        self.assertEqual(res_no_auth.status_code, 401)

        # Request con token inválido
        res_bad_token = client.post(
            '/api/leads/meta', 
            headers={'Authorization': 'Bearer token_falso_invalido_123'},
            json={'nombre': 'Test', 'telefono': '11223344'}
        )
        self.assertEqual(res_bad_token.status_code, 401)

        # Request con token válido por querystring o Bearer
        token_valido = os.environ.get('META_AI_WEBHOOK_TOKEN') or db.get_config('meta_ai_webhook_token') or 'crm_secure_webhook_token'
        res_ok_auth = client.post(
            '/api/leads/meta',
            headers={'Authorization': f"Bearer {token_valido}"},
            json={'nombre': 'Lead Seguro', 'telefono': '1199998888', 'mensaje_original': 'Hola'}
        )
        self.assertIn(res_ok_auth.status_code, [200, 201])
        print(" [PASS] Test 5: Meta AI webhook enforces strict token verification.")

    def test_06_busquedas_clientes_idor_defense(self):
        """Verifica que un agente no pueda borrar búsquedas de clientes de otros agentes (Anti-IDOR)."""
        from werkzeug.security import generate_password_hash
        pw_hash = generate_password_hash('123')

        # 1. Crear dos usuarios válidos para satisfacer foreign key
        owner_user = db.get_usuario('OwnerAgentTest')
        if not owner_user:
            owner_uid = db.insert_usuario('OwnerAgentTest', pw_hash, 'Owner Agent', 'agente', 'owner_test.db')
        else:
            owner_uid = owner_user['id']

        attacker_user = db.get_usuario('AttackerAgentTest')
        if not attacker_user:
            attacker_uid = db.insert_usuario('AttackerAgentTest', pw_hash, 'Attacker Agent', 'agente', 'attacker_test.db')
        else:
            attacker_uid = attacker_user['id']

        # 2. Obtener o crear contacto base
        contactos = db.get_contactos()
        if not contactos:
            cid = db.insert_contacto({'nombre': 'Cliente', 'apellido': 'Prueba', 'telefono': '1199990000'})
        else:
            cid = contactos[0]['id']

        # 3. Insertar búsqueda perteneciente al agente Owner
        bid = db.insert_busqueda_cliente({
            'cliente_id': cid,
            'nombre': 'Busqueda Agente Ajeno',
            'zona': 'Palermo',
            'agente_id': owner_uid
        })
        self.assertIsNotNone(bid)

        # 4. Iniciar sesión como AttackerAgent y tratar de borrar la búsqueda de OwnerAgent
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['_user_id'] = str(attacker_uid)
            sess['_fresh'] = True

        # Intento de borrado vía POST sobre búsqueda ajena
        res = client.post(f'/busquedas/clientes/{bid}/borrar', follow_redirects=True)
        self.assertIn(b"Acceso denegado", res.data)

        # Verificar que la búsqueda NO fue borrada de la base de datos
        b_despues = db.get_busqueda_cliente(bid)
        self.assertIsNotNone(b_despues, "La búsqueda ajena no debe haber sido borrada por un agente que no es dueño")

        # 5. Iniciar sesión como SuperAdmin GermanMazza y borrar legítimamente
        admin_client = app.test_client()
        admin_user = db.get_usuario('GermanMazza')
        with admin_client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user['id'])
            sess['_fresh'] = True

        res_admin = admin_client.post(f'/busquedas/clientes/{bid}/borrar', follow_redirects=True)
        self.assertIn(b"eliminada", res_admin.data)
        self.assertIsNone(db.get_busqueda_cliente(bid))

        print(" [PASS] Test 6: IDOR Defense successfully prevents cross-agent deletions.")


if __name__ == '__main__':
    unittest.main()
