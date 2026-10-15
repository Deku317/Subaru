import pdfplumber
import re
from thefuzz import process

class ExtractorFinanciero:
    def __init__(self, ruta_pdf):
        self.ruta_pdf = ruta_pdf
        self.lineas_texto = []
        self.datos_liquidez = {}
        self.datos_solvencia = {}
        self.datos_suficiencia = {}
        self.datos_reaseguro = {}
        self.datos_rentabilidad = {}

    def cargar_pdf_hibrido(self, paginas_dos_columnas=[0]):

        try:
            with pdfplumber.open(self.ruta_pdf) as pdf:
                for num_pagina, pagina in enumerate(pdf.pages):
                    
                    if num_pagina in paginas_dos_columnas:
                        # --- LÓGICA DE DOS COLUMNAS (Balance General) ---
                        ancho = pagina.width
                        alto = pagina.height
                        
                        mitad_izq = pagina.crop((0, 0, ancho / 2, alto))
                        mitad_der = pagina.crop((ancho / 2, 0, ancho, alto))
                        
                        texto_izq = mitad_izq.extract_text()
                        texto_der = mitad_der.extract_text()
                        
                        if texto_izq:
                            self.lineas_texto.extend([linea.strip() for linea in texto_izq.split('\n') if linea.strip()])
                        if texto_der:
                            self.lineas_texto.extend([linea.strip() for linea in texto_der.split('\n') if linea.strip()])
                            
                    else:
                        # --- LÓGICA DE UNA COLUMNA (Estado de Resultados) ---
                        texto = pagina.extract_text()
                        
                        if texto:
                            self.lineas_texto.extend([linea.strip() for linea in texto.split('\n') if linea.strip()])
                            
            print("PDF procesado: Balance y Estado de Resultados unificados con éxito.")
            
        except Exception as e:
            print(f"Error al cargar el PDF: {e}")

    def extraer_valor_inteligente(self, cuenta_objetivo, umbral_similitud=80):
        """
        Busca una cuenta usando inteligencia de similitud y extrae el valor.
        
        """
        
        nombres_lineas = [re.sub(r'[\d\.,\$\(\)]', '', linea).strip() for linea in self.lineas_texto]
        
        mejor_coincidencia, puntaje = process.extractOne(cuenta_objetivo, nombres_lineas)
        
        if puntaje >= umbral_similitud:
            indice = nombres_lineas.index(mejor_coincidencia)
            linea_original = self.lineas_texto[indice]
            
            linea_sin_espacios = re.sub(r'(?<=\d)\s*,\s*(?=\d)', ',', linea_original)
            
            # Atrapa números normales y números envueltos en ( )
            regex = r'\(?\s*-?\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*\)?|-?\d+(?:\.\d+)?'
            numeros = re.findall(regex, linea_sin_espacios)
            
            if numeros:
                # Tomamos el último fragmento atrapado
                cadena_num = numeros[-1]
                
                # 1. Detectar si es negativo (si tiene paréntesis '(' o un signo menos '-')
                es_negativo = '(' in cadena_num or '-' in cadena_num
                
                # 2. Limpiar el texto de todo lo que no sea dígito o punto (borra las comas y los paréntesis)
                cadena_limpia = re.sub(r'[^\d\.]', '', cadena_num)
                
                # 3. Convertir a float
                valor_limpio = float(cadena_limpia)
                
                # 4. Aplicar el signo si corresponde
                if es_negativo:
                    valor_limpio = -valor_limpio
                    
                return valor_limpio
                
        return None
    def calcular_cuenta_agregada(self, lista_subcuentas):
        """
        Suma una lista de subcuentas. Si una subcuenta no existe en el PDF,
        la trata como 0 para no romper el programa.
        """
        total = 0.0
        for cuenta in lista_subcuentas:
            valor = self.extraer_valor_inteligente(cuenta)
            
            # Manejo de errores: Si devuelve None (no encontró la cuenta), sumamos 0
            if valor is not None:
                total += valor
            else:
                print(f"Aviso interno: Subcuenta '{cuenta}' no encontrada. Se asume 0.")
                
        return total

    def capturar_datos_liquidez(self):
        """Extrae cuentas directas y calcula las agregadas según especificaciones."""
        
        # 1. Definimos de qué está compuesto el Activo Circulante 
        subcuentas_activo_circulante = [
            "Bancos",  
            "Deudores"
        ]
        subcuentas_pasivo_circulante = [
            "Acreedores",
            "Reaseguradores y Reafianzadores"
        ]
        subcuentas_activo_disponible = [
            "Inversiones",
            "Bancos"
        ]
        subcuentas_pasivo_exigible = [
            "Pólizas vencidas y Siniestros ocurridos pendientes de pago",
            "Acreedores",
            "Reaseguradores y Reafianzadores",
            "Provisión para la Participacion de los Trabajadores en la Utilidad",
            "Provisión para el pago de impuestos"
        ]

         #Calculamos las sumas y/o agregamos las cuentas
        self.datos_liquidez['activo_circulante'] = self.calcular_cuenta_agregada(subcuentas_activo_circulante)
        self.datos_liquidez['pasivo_circulante'] = self.calcular_cuenta_agregada(subcuentas_pasivo_circulante)
        self.datos_liquidez['activo_disponible'] = self.calcular_cuenta_agregada(subcuentas_activo_disponible)
        self.datos_liquidez['pasivo_exigible'] = self.calcular_cuenta_agregada(subcuentas_pasivo_exigible)
        self.datos_liquidez['reservas_tecnicas'] = self.extraer_valor_inteligente("reservas técnicas")
        self.datos_liquidez['inversiones'] = self.extraer_valor_inteligente("Inversiones")
        return self.datos_liquidez
    def capturar_datos_solvencia(self):
        self.datos_solvencia['activo_total'] = self.extraer_valor_inteligente("Suma Activo")
        self.datos_solvencia['pasivo_total'] = self.extraer_valor_inteligente("Suma Pasivo")
        self.datos_solvencia['activo-fijo'] = self.extraer_valor_inteligente("Otros activos")
        self.datos_solvencia['reserva_riesgos_curso'] = self.extraer_valor_inteligente("Reserva riesgos en curso")
        self.datos_solvencia['reserva_oblipendientes'] = self.extraer_valor_inteligente("Reserva obligaciones pendientes de cumplir")
        self.datos_solvencia['capital_contabletotal'] = self.extraer_valor_inteligente("Suma Capital")
        return self.datos_solvencia
    def capturar_datos_suficiencia_prima(self):
        self.datos_suficiencia['costo_operacion'] = self.extraer_valor_inteligente("gastos de operacion netos")
        self.datos_suficiencia['prima_emitida'] = self.extraer_valor_inteligente("emitida")
        self.datos_suficiencia['costo_netoa'] = self.extraer_valor_inteligente("Costo Neto de Adqusición")
        self.datos_suficiencia['prima_retenida'] = self.extraer_valor_inteligente("de retencion")
        self.datos_suficiencia['costo_siniestralidad'] = self.extraer_valor_inteligente("Costo neto de siniestralidad, reclamaciones y otras obligaciones pendientes")
        self.datos_suficiencia['prima_re_devengadas'] = self.extraer_valor_inteligente("Primas de retencion devengadas")
        return self.datos_suficiencia
    def capturar_datos_reaseguro(self):
        self.datos_reaseguro['prima_emitida'] = self.extraer_valor_inteligente("emitidas")
        self.datos_reaseguro['prima_cedida'] = self.extraer_valor_inteligente("cedidas")
        self.datos_reaseguro['prima_retenida'] = self.extraer_valor_inteligente("de retencion")
        self.datos_reaseguro['comision_re_cedido'] = self.extraer_valor_inteligente("Comision del reaseguro cedido")
        return self.datos_reaseguro
    def capturar_datos_rentabilidad(self):
        self.datos_rentabilidad['utilidad_neta'] = self.extraer_valor_inteligente("Resultado o remanente del ejercicio")
        self.datos_rentabilidad['capital_contabletotal'] = self.extraer_valor_inteligente("Suma Capital")
        self.datos_rentabilidad['capital_pagado'] = self.extraer_valor_inteligente("Capital contribuido")
        self.datos_rentabilidad['prima_directa'] = self.extraer_valor_inteligente("emitida")
        return self.datos_rentabilidad
    def ejecutar_extraccion_completa(self):
        """Función maestra que ejecuta todos los submódulos de extracción."""
        
        print("Iniciando extracción de datos...")
        datos_completos = {}
        
        #Unificamos todos los diccionarios en uno solo
        datos_completos.update(self.capturar_datos_liquidez())
        datos_completos.update(self.capturar_datos_solvencia())
        datos_completos.update(self.capturar_datos_rentabilidad())
        datos_completos.update(self.capturar_datos_reaseguro())
        datos_completos.update(self.capturar_datos_suficiencia_prima())

        # Extraemos los totales generales para validar
        activo_total = self.extraer_valor_inteligente("Suma Activo")
        pasivo_total = self.extraer_valor_inteligente("Suma Pasivo")
        capital_total = self.extraer_valor_inteligente("Suma Capital")
        
        if activo_total and pasivo_total and capital_total:
            #margen de error mínimo por los decimales
            diferencia = abs(activo_total - (pasivo_total + capital_total))
            if diferencia > 1.0:
                print(f"La ecuación contable no cuadra. Activos ≠ Pasivos + Capital")
                
            else:
                print("Validación financiera superada: Activo = Pasivo + Capital")
        
        return datos_completos
        
        
   
