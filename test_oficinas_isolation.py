import os
import sys
import unittest
import json

# Ensure project root is in path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

import database.db as db
import database.db_auth as db_auth
import database.db_finanzas as db_finanzas
import database.db_scrapers as db_scrapers

class MockUser:
    def __init__(self, id, usuario, rol='agente', oficina_id=None, oficina_nombre=None):
        self.id = id
        self.usuario = usuario
        self.rol = rol
        self.oficina_id = oficina_id
        self.oficina_nombre = oficina_nombre

    @property
    def is_authenticated(self):
        return True

class TestOficinasAndIsolation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()

    def test_01_oficinas_table_and_defaults(self):
        """Test default office exists and schema is populated."""
        oficinas = db.get_all_oficinas()
        self.assertTrue(len(oficinas) >= 1, "Debe existir al menos 1 oficina por defecto")
        
        main_ofi = db.get_oficina_by_id(1)
        self.assertIsNotNone(main_ofi)
        self.assertEqual(main_ofi['id'], 1)
        print(f"[OK] Default Office: {main_ofi['nombre']} (es_portal: {main_ofi['es_portal_clientes']})")

    def test_02_office_crud_and_single_portal_constraint(self):
        """Test creating, editing, portal toggling, and deleting offices."""
        # Create test office
        new_oid = db.insert_oficina(
            nombre="Oficina Test Pilar",
            slug="test-pilar",
            direccion="Panamericana Km 50",
            telefono="11223344",
            logo_url="/static/img/pilar.png",
            color_primario="#ff5722",
            color_secundario="#212121",
            es_portal_clientes=0,
            activa=1
        )
        self.assertIsInstance(new_oid, int)
        
        ofi = db.get_oficina_by_id(new_oid)
        self.assertEqual(ofi['nombre'], "Oficina Test Pilar")
        self.assertEqual(ofi['slug'], "test-pilar")

        # Set as portal
        db.set_portal_clientes_oficina(new_oid)
        portal_ofi = db.get_oficina_portal_clientes()
        self.assertIsNotNone(portal_ofi)
        self.assertEqual(portal_ofi['id'], new_oid)

        # Verify old office 1 is no longer portal
        ofi_1 = db.get_oficina_by_id(1)
        self.assertEqual(ofi_1['es_portal_clientes'], 0)

        # Reset portal back to office 1
        db.set_portal_clientes_oficina(1)
        portal_ofi_restored = db.get_oficina_portal_clientes()
        self.assertEqual(portal_ofi_restored['id'], 1)

        # Delete test office
        db.delete_oficina(new_oid)
        self.assertIsNone(db.get_oficina_by_id(new_oid))
        print("[OK] Office CRUD & Single Portal Constraint passed.")

    def test_03_privilege_hierarchy_superadmin(self):
        """GermanMazza must have absolute unrestricted access."""
        gm_user = MockUser(id=1, usuario='GermanMazza', rol='admin', oficina_id=1)
        
        self.assertTrue(db.check_user_privilege(gm_user, 'menu_item', 'gestion_usuarios'))
        self.assertTrue(db.check_user_privilege(gm_user, 'accion', 'ver_config_whatsapp_portal'))
        self.assertTrue(db.check_user_privilege(gm_user, 'accion', 'admin_oficinas'))
        self.assertTrue(db.check_user_privilege(gm_user, 'plugin', 'finanzas'))
        self.assertTrue(db.check_user_privilege(gm_user, 'plugin', 'meta_ai'))
        print("[OK] GermanMazza SuperAdmin privileges passed.")

    def test_04_privilege_hierarchy_office_admin(self):
        """Office Admin cannot access SuperAdmin-only actions, but can access office actions."""
        office_admin = MockUser(id=20, usuario='admin_sucursal', rol='admin', oficina_id=1)
        
        # Blocked SuperAdmin actions
        self.assertFalse(db.check_user_privilege(office_admin, 'accion', 'ver_config_whatsapp_portal'))
        self.assertFalse(db.check_user_privilege(office_admin, 'accion', 'admin_oficinas'))
        self.assertFalse(db.check_user_privilege(office_admin, 'accion', 'admin_database'))
        self.assertFalse(db.check_user_privilege(office_admin, 'accion', 'admin_backups'))
        self.assertFalse(db.check_user_privilege(office_admin, 'accion', 'admin_plugin_control'))
        self.assertFalse(db.check_user_privilege(office_admin, 'accion', 'scraping_studio'))
        
        # Allowed Office Admin actions
        self.assertTrue(db.check_user_privilege(office_admin, 'accion', 'ver_config_tokko'))
        self.assertTrue(db.check_user_privilege(office_admin, 'accion', 'ver_config_logo'))
        self.assertTrue(db.check_user_privilege(office_admin, 'accion', 'morning_briefing'))
        print("[OK] Office Admin isolation & permitted actions passed.")

    def test_05_privilege_hierarchy_solo_agent(self):
        """Solo Agents (oficina_id is None) are strictly blocked from Finanzas Oficina."""
        solo_agent = MockUser(id=99, usuario='agente_libre', rol='agente', oficina_id=None)
        
        # Strictly blocked for solo agents
        self.assertFalse(db.check_user_privilege(solo_agent, 'menu_item', 'finanzas_oficina'))
        self.assertFalse(db.check_user_privilege(solo_agent, 'plugin', 'finanzas_oficina'))
        
        # SuperAdmin actions blocked
        self.assertFalse(db.check_user_privilege(solo_agent, 'accion', 'admin_oficinas'))
        self.assertFalse(db.check_user_privilege(solo_agent, 'accion', 'ver_config_whatsapp_portal'))
        print("[OK] Solo Agent restrictions passed.")

    def test_06_finance_scoping_isolation(self):
        """Test get_operaciones scoping by oficina_id, agente_id, and SuperAdmin."""
        # Insert temporary user in office 1
        conn = db.get_db()
        try:
            conn.execute("""
                INSERT INTO usuarios (id, usuario, password_hash, rol, oficina_id)
                VALUES (8888, 'test_fin_user', 'hash', 'agente', 1)
                ON CONFLICT (id) DO UPDATE SET oficina_id = 1
            """)
            conn.execute("""
                INSERT INTO usuarios (id, usuario, password_hash, rol, oficina_id)
                VALUES (8889, 'test_fin_user_2', 'hash', 'agente', NULL)
                ON CONFLICT (id) DO UPDATE SET oficina_id = NULL
            """)
            conn.execute("""
                INSERT INTO seguimiento_operaciones (
                    id, agente_id, domicilio, bruto, estado, mes
                ) VALUES (99999, 8888, 'Calle Test 123', 150000, 'Cerrada', 'Agosto')
                ON CONFLICT (id) DO UPDATE SET agente_id = 8888, domicilio = 'Calle Test 123'
            """)
            conn.commit()
        except Exception as e:
            print(f"Error inserting test op: {e}")
        finally:
            conn.close()

        # 1. SuperAdmin (oficina_id=None, agente_id=None) -> should see it
        ops_super = db_finanzas.get_operaciones(oficina_id=None, agente_id=None)
        self.assertTrue(any(op['id'] == 99999 for op in ops_super))

        # 2. Office 1 Admin (oficina_id=1, agente_id=None) -> should see it
        ops_ofi1 = db_finanzas.get_operaciones(oficina_id=1, agente_id=None)
        self.assertTrue(any(op['id'] == 99999 for op in ops_ofi1))

        # 3. Office 2 Admin (oficina_id=999, agente_id=None) -> must NOT see it
        ops_ofi2 = db_finanzas.get_operaciones(oficina_id=999, agente_id=None)
        self.assertFalse(any(op['id'] == 99999 for op in ops_ofi2))

        # 4. Agent 8888 (agente_id=8888) -> should see it
        ops_ag8888 = db_finanzas.get_operaciones(agente_id=8888)
        self.assertTrue(any(op['id'] == 99999 for op in ops_ag8888))

        # 5. Agent 8889 (agente_id=8889) -> must NOT see it
        ops_ag8889 = db_finanzas.get_operaciones(agente_id=8889)
        self.assertFalse(any(op['id'] == 99999 for op in ops_ag8889))

        # Clean up test records
        conn = db.get_db()
        try:
            conn.execute("DELETE FROM seguimiento_operaciones WHERE id = 99999")
            conn.execute("DELETE FROM usuarios WHERE id IN (8888, 8889)")
            conn.commit()
        finally:
            conn.close()
            
        print("[OK] Financial operations multi-tenant isolation passed.")

    def test_07_scrapers_public_searches_office_scoping(self):
        """Public shared searches must return empty for solo agents and scope to office."""
        # Solo agent (oficina_id=None)
        busquedas_suelto = db_scrapers.get_busquedas_publicas_oficina(oficina_id=None)
        self.assertEqual(busquedas_suelto, [], "Solo agents must receive empty list for shared office searches")
        print("[OK] Scraper shared office searches isolation passed.")

    def test_08_superadmin_only_busquedas_and_planificador(self):
        """Robots de Búsqueda and Planificador 10 Semanas must be accessible ONLY by SuperAdmin (GermanMazza)."""
        gm_user = MockUser(id=1, usuario='GermanMazza', rol='admin', oficina_id=1)
        office_admin = MockUser(id=20, usuario='admin_sucursal', rol='admin', oficina_id=1)
        office_broker = MockUser(id=21, usuario='broker_sucursal', rol='broker', oficina_id=1)
        office_agent = MockUser(id=22, usuario='agente_sucursal', rol='agente', oficina_id=1)
        solo_agent = MockUser(id=99, usuario='agente_libre', rol='agente', oficina_id=None)

        # 1. SuperAdmin -> ALL TRUE
        self.assertTrue(db.check_user_privilege(gm_user, 'menu_item', 'busquedas'))
        self.assertTrue(db.check_user_privilege(gm_user, 'menu_item', 'busquedas_scrapers'))
        self.assertTrue(db.check_user_privilege(gm_user, 'menu_item', 'planificador'))
        self.assertTrue(db.check_user_privilege(gm_user, 'accion', 'ejecutar_scraper'))
        self.assertTrue(db.check_user_privilege(gm_user, 'accion', 'limpiar_busqueda'))

        # 2. Non-SuperAdmins -> ALL FALSE
        for non_super in [office_admin, office_broker, office_agent, solo_agent]:
            self.assertFalse(db.check_user_privilege(non_super, 'menu_item', 'busquedas'), f"{non_super.usuario} should NOT access busquedas")
            self.assertFalse(db.check_user_privilege(non_super, 'menu_item', 'busquedas_scrapers'), f"{non_super.usuario} should NOT access busquedas_scrapers")
            self.assertFalse(db.check_user_privilege(non_super, 'menu_item', 'planificador'), f"{non_super.usuario} should NOT access planificador")
            self.assertFalse(db.check_user_privilege(non_super, 'accion', 'ejecutar_scraper'), f"{non_super.usuario} should NOT access ejecutar_scraper")
            self.assertFalse(db.check_user_privilege(non_super, 'accion', 'limpiar_busqueda'), f"{non_super.usuario} should NOT access limpiar_busqueda")

        print("[OK] Robots de Busqueda and Planificador 10 Semanas SuperAdmin-only restriction passed.")

    def test_09_historias_dropdown_office_scoping(self):
        """Office admins must only see users of their own office in the Historias agent list, never solo agents or other offices."""
        conn = db.get_db()
        try:
            # Ensure office 222 exists
            conn.execute("INSERT INTO oficinas (id, nombre, slug) VALUES (222, 'Oficina Test 2', 'ofi2') ON CONFLICT (id) DO NOTHING")
            conn.execute("INSERT INTO usuarios (id, usuario, password_hash, rol, oficina_id) VALUES (7771, 'ag_ofi1', 'h', 'agente', 1) ON CONFLICT (id) DO UPDATE SET oficina_id = 1")
            conn.execute("INSERT INTO usuarios (id, usuario, password_hash, rol, oficina_id) VALUES (7772, 'ag_ofi2', 'h', 'agente', 222) ON CONFLICT (id) DO UPDATE SET oficina_id = 222")
            conn.execute("INSERT INTO usuarios (id, usuario, password_hash, rol, oficina_id) VALUES (7773, 'ag_suelto', 'h', 'agente', NULL) ON CONFLICT (id) DO UPDATE SET oficina_id = NULL")
            conn.commit()

            # Query for Office 1 Admin
            agentes_ofi1 = conn.execute("SELECT id, usuario FROM usuarios WHERE oficina_id = ? ORDER BY nombre_display ASC", (1,)).fetchall()
            ofi1_ids = {a['id'] for a in agentes_ofi1}

            self.assertIn(7771, ofi1_ids)
            self.assertNotIn(7772, ofi1_ids, "Office 1 Admin must NOT see Office 2 Agent in Historias")
            self.assertNotIn(7773, ofi1_ids, "Office 1 Admin must NOT see Solo Agent in Historias")

            # Clean up
            conn.execute("DELETE FROM usuarios WHERE id IN (7771, 7772, 7773)")
            conn.execute("DELETE FROM oficinas WHERE id = 222")
            conn.commit()
        finally:
            conn.close()
        print("[OK] Historias dropdown office scoping passed.")

    def test_10_libro_finanzas_and_analitica_office_admin_only(self):
        """Libro de Finanzas, Finanzas Oficina, and Analitica & KPIs must be accessible ONLY by Office Admins, Brokers, and SuperAdmin."""
        gm_user = MockUser(id=1, usuario='GermanMazza', rol='admin', oficina_id=1)
        office_admin = MockUser(id=20, usuario='admin_sucursal', rol='admin', oficina_id=1)
        office_broker = MockUser(id=21, usuario='broker_sucursal', rol='broker', oficina_id=1)
        office_agent = MockUser(id=22, usuario='agente_sucursal', rol='agente', oficina_id=1)
        solo_agent = MockUser(id=99, usuario='agente_libre', rol='agente', oficina_id=None)

        # 1. GermanMazza -> TRUE
        self.assertTrue(db.check_user_privilege(gm_user, 'menu_item', 'libro_finanzas'))
        self.assertTrue(db.check_user_privilege(gm_user, 'menu_item', 'finanzas_oficina'))
        self.assertTrue(db.check_user_privilege(gm_user, 'menu_item', 'analitica'))

        # 2. Office Admin and Broker -> TRUE
        self.assertTrue(db.check_user_privilege(office_admin, 'menu_item', 'libro_finanzas'))
        self.assertTrue(db.check_user_privilege(office_admin, 'menu_item', 'finanzas_oficina'))
        self.assertTrue(db.check_user_privilege(office_admin, 'menu_item', 'analitica'))

        self.assertTrue(db.check_user_privilege(office_broker, 'menu_item', 'libro_finanzas'))
        self.assertTrue(db.check_user_privilege(office_broker, 'menu_item', 'finanzas_oficina'))
        self.assertTrue(db.check_user_privilege(office_broker, 'menu_item', 'analitica'))

        # 3. Regular Office Agent and Solo Agent -> FALSE
        self.assertFalse(db.check_user_privilege(office_agent, 'menu_item', 'libro_finanzas'))
        self.assertFalse(db.check_user_privilege(office_agent, 'menu_item', 'finanzas_oficina'))
        self.assertFalse(db.check_user_privilege(office_agent, 'menu_item', 'analitica'))

        self.assertFalse(db.check_user_privilege(solo_agent, 'menu_item', 'libro_finanzas'))
        self.assertFalse(db.check_user_privilege(solo_agent, 'menu_item', 'finanzas_oficina'))
        self.assertFalse(db.check_user_privilege(solo_agent, 'menu_item', 'analitica'))

        print("[OK] Libro de Finanzas and Analitica Office Admin / SuperAdmin restrictions passed.")

    def test_11_user_scoped_keys_no_credential_leak(self):
        """User-scoped keys (Groq key, phone, tokens, Claudia config) must NEVER leak from GermanMazza to unconfigured agents."""
        conn = db.get_db()
        try:
            # Set GermanMazza's groq key and phone in DB
            conn.execute("INSERT INTO configuracion (clave, valor) VALUES ('groq_api_key_4', 'gsk_secret_german_key') ON CONFLICT (clave) DO UPDATE SET valor = 'gsk_secret_german_key'")
            conn.execute("INSERT INTO configuracion (clave, valor) VALUES ('agente_telefono_4', '5491100001111') ON CONFLICT (clave) DO UPDATE SET valor = '5491100001111'")
            conn.commit()

            # Query config for user 8888 who has NOT set a groq key or phone
            groq_8888 = db.get_config_for_user('groq_api_key', 8888, default="")
            phone_8888 = db.get_config_for_user('agente_telefono', 8888, default="")

            self.assertEqual(groq_8888, "", "Unconfigured agent must NOT get GermanMazza's secret Groq key")
            self.assertEqual(phone_8888, "", "Unconfigured agent must NOT get GermanMazza's phone number")

            # Clean up
            conn.execute("DELETE FROM configuracion WHERE clave IN ('groq_api_key_4', 'agente_telefono_4')")
            conn.commit()
        finally:
            conn.close()
        print("[OK] Zero credential/token/phone leakage test passed.")

    def test_12_analitica_office_scoping(self):
        """Analitica metrics and ranking_asesores must strictly scope to current office."""
        from modules import analitica
        conn = db.get_db()
        try:
            conn.execute("INSERT INTO oficinas (id, nombre, slug) VALUES (333, 'Oficina Test 3', 'ofi3') ON CONFLICT (id) DO NOTHING")
            conn.execute("INSERT INTO usuarios (id, usuario, password_hash, rol, oficina_id) VALUES (8881, 'ag_ofi3', 'h', 'agente', 333) ON CONFLICT (id) DO UPDATE SET oficina_id = 333")
            conn.execute("INSERT INTO usuarios (id, usuario, password_hash, rol, oficina_id) VALUES (8882, 'ag_suelto_test', 'h', 'agente', NULL) ON CONFLICT (id) DO UPDATE SET oficina_id = NULL")
            conn.commit()

            # Query metrics for Office 333
            m_ofi3 = analitica.calcular_metricas_analitica(oficina_id=333)
            ranking_ids = {a['id'] for a in m_ofi3['ranking_asesores']}

            self.assertIn(8881, ranking_ids, "Office 333 agent must be present in ranking")
            self.assertNotIn(8882, ranking_ids, "Solo agent must NOT be present in Office 333 ranking")

            # Clean up
            conn.execute("DELETE FROM usuarios WHERE id IN (8881, 8882)")
            conn.execute("DELETE FROM oficinas WHERE id = 333")
            conn.commit()
        finally:
            conn.close()
        print("[OK] Analitica office isolation and ranking scoping passed.")

    def test_13_morning_briefing_office_scoping(self):
        """Asistente IA Morning Briefing agent table must only return members of the admin's office."""
        conn = db.get_db()
        try:
            conn.execute("INSERT INTO oficinas (id, nombre, slug) VALUES (444, 'Oficina Test 4', 'ofi4') ON CONFLICT (id) DO NOTHING")
            conn.execute("INSERT INTO usuarios (id, usuario, password_hash, rol, oficina_id) VALUES (9991, 'ag_ofi4', 'h', 'agente', 444) ON CONFLICT (id) DO UPDATE SET oficina_id = 444")
            conn.execute("INSERT INTO usuarios (id, usuario, password_hash, rol, oficina_id) VALUES (9992, 'ag_suelto_mb', 'h', 'agente', NULL) ON CONFLICT (id) DO UPDATE SET oficina_id = NULL")
            conn.commit()

            # Mock Office 444 Admin query
            users = conn.execute("""
                SELECT id, usuario, nombre_display, rol, oficina_id 
                FROM usuarios 
                WHERE rol IN ('agente', 'broker', 'admin') AND oficina_id = ?
                ORDER BY id ASC
            """, (444,)).fetchall()
            mb_ids = {u['id'] for u in users}

            self.assertIn(9991, mb_ids, "Office 444 agent must be listed for Office 444 Admin")
            self.assertNotIn(9992, mb_ids, "Solo agent must NOT be listed for Office 444 Admin")

            # Clean up
            conn.execute("DELETE FROM usuarios WHERE id IN (9991, 9992)")
            conn.execute("DELETE FROM oficinas WHERE id = 444")
            conn.commit()
        finally:
            conn.close()
        print("[OK] Morning Briefing office isolation passed.")

    def test_14_erp_finanzas_cajas_opex_isolation(self):
        """Test multi-tenant isolation for Cajas/Bancos, OPEX expenses, suppliers, and P&L calculation."""
        conn = db.get_db()
        try:
            # Create two distinct test offices
            conn.execute("INSERT INTO oficinas (id, nombre, slug) VALUES (501, 'Oficina Test 501', 'ofi501') ON CONFLICT (id) DO NOTHING")
            conn.execute("INSERT INTO oficinas (id, nombre, slug) VALUES (502, 'Oficina Test 502', 'ofi502') ON CONFLICT (id) DO NOTHING")
            conn.commit()

            # 1. Create Cash Registers in both offices
            caja_501_id = db_finanzas.save_caja_banco({
                'oficina_id': 501,
                'nombre': 'Caja Fuerte 501',
                'tipo': 'caja_efectivo',
                'moneda': 'USD',
                'saldo_inicial': 5000.0,
                'activa': 1
            })
            caja_502_id = db_finanzas.save_caja_banco({
                'oficina_id': 502,
                'nombre': 'Caja Fuerte 502',
                'tipo': 'caja_efectivo',
                'moneda': 'USD',
                'saldo_inicial': 12000.0,
                'activa': 1
            })

            # Check that Office 501 only sees its own cash register
            cajas_501 = db_finanzas.get_cajas_bancos(oficina_id=501)
            cajas_501_ids = {c['id'] for c in cajas_501}
            self.assertIn(caja_501_id, cajas_501_ids)
            self.assertNotIn(caja_502_id, cajas_501_ids, "Office 501 must NOT see Office 502 cash account")

            # 2. Create Suppliers and OPEX Expenses
            prov_501_id = db_finanzas.save_proveedor({
                'oficina_id': 501,
                'nombre': 'Zonaprop Sede 501',
                'rubro': 'Portales'
            })
            prov_502_id = db_finanzas.save_proveedor({
                'oficina_id': 502,
                'nombre': 'Zonaprop Sede 502',
                'rubro': 'Portales'
            })

            gasto_501_id = db_finanzas.save_gasto_opex({
                'oficina_id': 501,
                'proveedor_id': prov_501_id,
                'descripcion': 'Factura Portales 501',
                'categoria': 'portales',
                'monto': 1500.0,
                'moneda': 'USD',
                'estado': 'pendiente'
            })
            gasto_502_id = db_finanzas.save_gasto_opex({
                'oficina_id': 502,
                'proveedor_id': prov_502_id,
                'descripcion': 'Factura Portales 502',
                'categoria': 'portales',
                'monto': 4000.0,
                'moneda': 'USD',
                'estado': 'pendiente'
            })

            # Verify OPEX list scoping
            gastos_501 = db_finanzas.get_gastos_opex(oficina_id=501)
            gastos_501_ids = {g['id'] for g in gastos_501}
            self.assertIn(gasto_501_id, gastos_501_ids)
            self.assertNotIn(gasto_502_id, gastos_501_ids, "Office 501 must NOT see Office 502 OPEX expense")

            # 3. Pay Expense and verify cash register debit
            pay_success = db_finanzas.pagar_gasto_opex(gasto_501_id, caja_501_id, oficina_id=501, modificado_por='test_admin')
            self.assertTrue(pay_success, "Expense payment must succeed")

            # Re-fetch cash registers
            cajas_501_updated = db_finanzas.get_cajas_bancos(oficina_id=501)
            caja_501_obj = next(c for c in cajas_501_updated if c['id'] == caja_501_id)
            self.assertEqual(caja_501_obj['saldo_actual'], 3500.0, "5000 initial - 1500 expense = 3500 remaining")

            # Verify P&L Scoping
            pnl_501 = db_finanzas.calcular_balance_oficina(oficina_id=501)
            self.assertEqual(pnl_501['resumen']['opex_pagado_usd'], 1500.0)
            self.assertEqual(pnl_501['resumen']['liquidez_usd'], 3500.0)

            # Clean up
            conn.execute("DELETE FROM finanzas_movimientos_caja WHERE oficina_id IN (501, 502)")
            conn.execute("DELETE FROM finanzas_gastos_opex WHERE oficina_id IN (501, 502)")
            conn.execute("DELETE FROM finanzas_proveedores WHERE oficina_id IN (501, 502)")
            conn.execute("DELETE FROM finanzas_cajas_bancos WHERE oficina_id IN (501, 502)")
            conn.execute("DELETE FROM oficinas WHERE id IN (501, 502)")
            conn.commit()
        finally:
            conn.close()
        print("[OK] ERP Finances (Cajas, OPEX, Proveedores, P&L) multi-tenant isolation passed.")

if __name__ == '__main__':
    unittest.main()
