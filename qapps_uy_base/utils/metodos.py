import pytz

from .label import COMA, SALTO_LINEA

TIMEZONE_BASE = "America/Montevideo"


def convert_local_date_to_utc(date_obj):
    date_obj_utc = False
    if date_obj:
        zk_timezone = pytz.timezone(TIMEZONE_BASE)
        date_obj = zk_timezone.localize(date_obj, is_dst=None)
        date_obj = date_obj.astimezone(pytz.utc)
        date_obj_utc = date_obj.replace(tzinfo=None)
    return date_obj_utc


def convert_utc_to_local(date_obj):
    date_obj_local = False
    if date_obj:
        zk_timezone = pytz.timezone(TIMEZONE_BASE)
        date_obj_dt = date_obj.replace(tzinfo=pytz.utc)
        date_obj_local = date_obj_dt.astimezone(zk_timezone)
        date_obj_local = date_obj_local.replace(tzinfo=None)
    return date_obj_local


def concatenar_textos(texto_base, texto_nuevo, caracter=COMA):
    if not texto_base:
        texto_base = ""

    if not texto_nuevo:
        return texto_base

    if texto_base:
        if caracter == SALTO_LINEA:
            texto_base += f"{caracter}"
        else:
            texto_base += f"{caracter} "
    texto_base += texto_nuevo
    return texto_base


def is_partner_ruc(partner_id):
    tipo_doc = partner_id.tipo_doc or False
    vat = partner_id.vat or False
    return tipo_doc == "2" and vat and len(vat) > 2


def get_value_active_domain(context, key):
    if context.get("active_domain", False):
        for v in context.get("active_domain", False):
            if key == v[0]:
                return v[2]
    return False
