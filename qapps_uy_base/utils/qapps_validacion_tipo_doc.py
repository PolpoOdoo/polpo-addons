import math


def validacion_ruc(ruc):
    if not ruc.isdigit():
        return False
    """
    • Las dos primeras posiciones estén en el rango 01 a 22.
    • De la 3a. a la 8va. posición debe ser distinto de 000000
    • Las posiciones 9a. y 10a. deben ser 00.
    """
    if (
        len(ruc) != 12
        or ruc[:2] < "01"
        or ruc[:2] > "22"
        or ruc[2:8] == "000000"
        or ruc[8:10] != "00"
    ):
        return False

    factor = [4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    suma = 0
    for i in range(0, 11):
        suma += int(ruc[i]) * factor[i]

    resto = suma % 11
    digito = 11 - resto
    if digito == 11:
        digito = 0
    if digito != int(ruc[-1:]):
        return False
    return True


def validacion_ci(ci):
    if not ci.isdigit():
        return False

    if len(ci) != 8:
        return False

    factor = [2, 9, 8, 7, 6, 3, 4]
    suma = 0
    for i in range(0, 7):
        suma += int(ci[i]) * factor[i]

    digito = (math.ceil(suma / 10) * 10) - suma
    if digito != int(ci[-1:]):
        return False
    return True
