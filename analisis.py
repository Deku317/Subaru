class AnalizadorFinanciero:
    def __init__(self, datos_extraidos):
        self.datos = datos_extraidos
        self.resultados = {}

    def division_segura(self, numerador, denominador):
        
        if numerador is None or denominador is None:
            return None
        if denominador == 0:
            return "Error (#DIV/0!)"
        return round(numerador / denominador, 4)

    def analizar_liquidez(self):
        
        a_circulante = self.datos.get('activo_circulante')
        p_circulante = self.datos.get('pasivo_circulante')
        inversiones = self.datos.get('inversiones')
        pasivo_e = self.datos.get('pasivo_exigible')
        reservas_tecnicas = self.datos.get('reservas_tecnicas')
        
        # Razón 1: Activo circulante / Pasivo circulante
        r1 = self.division_segura(a_circulante, p_circulante)
        # Razón 2: Inversiones / Reservas técnicas 
        r2 = self.division_segura(inversiones, pasivo_e)
        # Razón 3, 4 y 5 
        r3 = self.division_segura(self.datos.get('activo_circulante'), pasivo_e)
        r4 = self.division_segura(a_circulante, self.datos.get('reservas_tecnicas'))
        r5 = self.division_segura(self.datos.get('inversiones'), self.datos.get('pasivo_circulante'))

        self.resultados['Liquidez'] = {
            'Razon_1': r1, 'Razon_2': r2, 'Razon_3': r3, 'Razon_4': r4, 'Razon_5': r5,
            'Diagnostico': "Evaluación de los 5 niveles de liquidez calculados."
        }

    def analizar_solvencia_y_apalancamiento(self):
        """Las 2 Razones de Solvencia y 2 de Apalancamiento del Excel"""
        activo_t = self.datos.get('activo_total')
        pasivo_t = self.datos.get('pasivo_total')
        capital_t = self.datos.get('capital_contabletotal')
        reservas_tec = self.datos.get('reservas_tecnicas')
        reserva_rc = self.datos.get('reserva_riesgos_curso') # Rva Riesgos en Curso
        reserva_pen = self.datos.get('reserva_oblipendientes')

        # -- SOLVENCIA --
        # Razón 1: Activo Total / Pasivo Total
        solv1 = self.division_segura(activo_t, pasivo_t)
        # Razón 2: (Activo Total - Activo Fijo) / (Pasivo Total - Rva RC)
        activo_menos_fijo = (activo_t - self.datos.get('activo-fijo')) if activo_t and self.datos.get('activo-fijo') else None
        pasivo_menos_rc = (pasivo_t - reserva_rc - reserva_pen) if pasivo_t and reserva_rc and reserva_pen else None
        solv2 = self.division_segura(activo_menos_fijo, pasivo_menos_rc)

        # -- APALANCAMIENTO --
        # Razón 1: Pasivo Total / Capital Contable
        apal1 = self.division_segura(pasivo_t, capital_t)
        # Razón 2: Reservas Técnicas / Capital Contable
        apal2 = self.division_segura(reservas_tec, capital_t)

        self.resultados['Solvencia_Apalancamiento'] = {
            'Solvencia_1': solv1, 'Solvencia_2': solv2,
            'Apalancamiento_1': apal1, 'Apalancamiento_2': apal2,
            'Diagnostico': "Evaluación de solvencia y estructura de capital."
        }

    def analizar_suficiencia_prima(self):
        """Los 5 indicadores de Suficiencia de Prima del Excel"""
        cto_operacion = self.division_segura(self.datos.get('costo_operacion'), self.datos.get('prima_emitida'))
        cto_adquisicion = self.division_segura(self.datos.get('costo_netoa'), self.datos.get('prima_retenida'))
        cto_siniestralidad = self.division_segura(self.datos.get('costo_siniestralidad'), self.datos.get('prima_re_devengadas'))
        
        # Índice combinado (Suma de los 3 costos medios)
        if all(isinstance(x, float) for x in [cto_operacion, cto_adquisicion, cto_siniestralidad]):
            indice_combinado = cto_operacion + cto_adquisicion + cto_siniestralidad
            suficiencia = 1 - indice_combinado
            diag = "Rentable técnicamente" if suficiencia > 0 else "Pérdida técnica"
        else:
            indice_combinado, suficiencia, diag = None, None, "Faltan datos"

        self.resultados['Suficiencia_Prima'] = {
            'Cto_Medio_Operacion': cto_operacion,
            'Cto_Medio_Adquisicion': cto_adquisicion,
            'Cto_Medio_Siniestralidad': cto_siniestralidad,
            'Indice_Combinado': round(indice_combinado, 4) if indice_combinado else None,
            'Suficiencia_Prima': round(suficiencia, 4) if suficiencia else None,
            'Diagnostico': diag
        }

    def analizar_reaseguro(self):
        """Las 3 Razones de Reaseguro del Excel"""
        prima_emi = self.datos.get('prima_emitida')
        prima_ced = self.datos.get('prima_cedida')
        prima_ret = self.datos.get('prima_retenida')
        
        # Razón 1: Prima Cedida / Prima Emitida
        r1 = self.division_segura(prima_ced, prima_emi)
        # Razón 2: Prima Retenida / Prima Emitida
        r2 = self.division_segura(prima_ret, prima_emi)
        # Razón 3: Comisión Reaseguro / Prima Cedida
        r3 = self.division_segura(self.datos.get('comision_re_cedido'), prima_ced)

        self.resultados['Reaseguro'] = {
            'Razon_1_Cesion': r1,
            'Razon_2_Retencion': r2,
            'Razon_3_Comision': r3,
            'Diagnostico': f"Retención del {(r2*100):.2f}%" if isinstance(r2, float) else "Faltan datos"
        }

    def analizar_rentabilidad(self):
        """Las 3 Razones de Rentabilidad del Excel con manejo de Pérdidas"""
        utilidad = self.datos.get('utilidad_neta')
        capital_contable = self.datos.get('capital_contabletotal')
        capital_pagado = self.datos.get('capital_pagado')
        prima_directa = self.datos.get('prima_directa')
        
        # Razón 1: Utilidad / Capital Contable (ROE)
        r1 = self.division_segura(utilidad, capital_contable)
        # Razón 2: Utilidad / Capital Pagado
        r2 = self.division_segura(utilidad, capital_pagado)
        # Razón 3: Utilidad / Prima Directa (Margen)
        r3 = self.division_segura(utilidad, prima_directa)

        
        if isinstance(utilidad, float):
            if utilidad < 0:
                diagnostico = (f"Alerta: Pérdida Neta detectada. La operación destruyó valor en este periodo. "
                               f"El margen sobre primas es de {(r3*100):.2f}% (pérdida por cada peso vendido).")
            elif utilidad > 0:
                diagnostico = (f"Operación rentable. Genera un rendimiento positivo del {(r1*100):.2f}% "
                               f"sobre el capital contable (ROE).")
            else:
                diagnostico = "La empresa alcanzó el punto de equilibrio (Utilidad cero)."
        else:
            diagnostico = "Faltan datos para calcular la rentabilidad."

        self.resultados['Rentabilidad'] = {
            'Razon_1_ROE': r1,
            'Razon_2_Cap_Pagado': r2,
            'Razon_3_Margen_Primas': r3,
            'Diagnostico': diagnostico
        }
    def ejecutar_analisis_completo(self):
        self.analizar_liquidez()
        self.analizar_solvencia_y_apalancamiento()
        self.analizar_suficiencia_prima()
        self.analizar_reaseguro()
        self.analizar_rentabilidad()
        return self.resultados

