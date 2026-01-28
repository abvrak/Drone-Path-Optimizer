import math
import os
import arcpy
import requests
from arcpy.sa import CostDistance, CostPathAsPolyline
from arcpy.sa import Con, IsNull, Raster, Reclassify, RemapRange, Slope, Aspect, Abs, Mod

# ==========================================
# FUNKCJE POMOCNICZE (MATEMATYKA I PARSOWANIE)
# ==========================================

def parse_xy(value):
    """
    Konwertuje ciąg znaków (string) z parametru wejściowego na dwie liczby zmiennoprzecinkowe (float).
    Oczekuje formatu "X, Y" (np. "747945.82, 383931.63").
    UWAGA: Separator dziesiętny to kropka (.), a separator liczb to przecinek (,).
    """
    # Rozdzielenie tekstu po przecinku i usunięcie białych znaków (spacji)
    parts = [p.strip() for p in value.split(",")]
    # Zwraca krotkę (tuple) dwóch liczb
    return float(parts[0]), float(parts[1])


def bearing_deg(start_xy, end_xy):
    """
    Oblicza azymut geograficzny (kierunek lotu) w stopniach na podstawie dwóch punktów.
    Wynik: 0-360 stopni (0 = Północ, 90 = Wschód).
    """
    dx = end_xy[0] - start_xy[0]
    dy = end_xy[1] - start_xy[1]
    # math.atan2 zwraca wynik w radianach, konwertujemy na stopnie
    angle = math.degrees(math.atan2(dx, dy))
    # Normalizacja wyniku do zakresu 0-360 (atan2 może zwracać wartości ujemne)
    return (angle + 360.0) % 360.0


def wind_factor(wind_speed, wind_deg, route_bearing):
    """
    Oblicza współczynnik kary za wiatr.
    Zasada: Jeśli dron leci pod wiatr, koszt ruchu rośnie.
    route_bearing: kierunek trasy, wind_deg: kierunek, z którego wieje wiatr.
    """
    # Obliczenie różnicy kątowej między kierunkiem wiatru a trasą
    angle_diff = abs((wind_deg - route_bearing + 180.0) % 360.0 - 180.0)
    # Wzór heurystyczny: im silniejszy wiatr i gorszy kąt, tym wyższy mnożnik kosztu
    return max(0.6, 1.0 + (wind_speed / 15.0) * (angle_diff / 180.0))


# ==========================================
# INTEGRACJA Z ZEWNĘTRZNYM API (POGODA)
# ==========================================

def get_lublin_weather(api_key):
    """
    Pobiera aktualną pogodę dla Lublina z serwisu OpenWeatherMap.
    Zwraca prędkość wiatru (m/s) i kierunek (stopnie).
    """
    if not api_key or requests is None:
        return 0.0, 0.0

    url = (
        "https://api.openweathermap.org/data/2.5/weather"
        f"?q=Lublin,PL&appid={api_key}"
    )
    try:
        # Timeout 10s zapobiega zawieszeniu skryptu przy braku sieci
        data = requests.get(url, timeout=10).json()
        wind_speed = float(data.get("wind", {}).get("speed", 0.0))
        wind_deg = float(data.get("wind", {}).get("deg", 0.0))
        return wind_speed, wind_deg
    except Exception as e:
        arcpy.AddWarning(f"Nie udało się pobrać pogody: {e}. Przyjęto wiatr 0 m/s.")
        return 0.0, 0.0


# ==========================================
# OPERACJE NA GEOBAZIE I GEOMETRII (GIS)
# ==========================================

def create_point_fc(output_gdb, nmt_raster, name, point_xy):
    """
    Tworzy fizyczną warstwę punktową (Feature Class) w geobazie na podstawie współrzędnych X, Y.
    Jest to konieczne, ponieważ narzędzia 'Cost Distance' wymagają warstwy, a nie samych liczb.
    """
    fc_path = os.path.join(output_gdb, name)
    
    # Usuwamy starą warstwę, jeśli istnieje (nadpisywanie)
    if arcpy.Exists(fc_path):
        arcpy.management.Delete(fc_path)

    # Pobieramy układ współrzędnych z rastra wysokościowego (NMT), aby punkty pasowały do mapy
    spatial_ref = arcpy.Describe(nmt_raster).spatialReference
    
    arcpy.management.CreateFeatureclass(
        output_gdb, name, "POINT", spatial_reference=spatial_ref
    )
    arcpy.management.AddField(fc_path, "Name", "TEXT")
    
    # Wstawiamy punkt do nowej warstwy używając kursora (InsertCursor)
    with arcpy.da.InsertCursor(fc_path, ["SHAPE@", "Name"]) as cursor:
        point = arcpy.Point(point_xy[0], point_xy[1])
        cursor.insertRow([arcpy.PointGeometry(point, spatial_ref), name])
        
    return fc_path


# ==========================================
# GŁÓWNA LOGIKA ANALIZY PRZESTRZENNEJ
# ==========================================

def build_cost_raster(
    nmt_raster,
    buildings_fc,
    output_gdb,
    wind_speed,
    wind_deg,
    penalty,
    vegetation_raster,
    vegetation_penalty=3.0,
):
    """
    Tworzy raster kosztu (Cost Surface). Każda komórka rastra otrzymuje wartość
    reprezentującą "trudność" przelotu przez ten obszar.
    Czynniki: nachylenie terenu, budynki, wiatr, roślinność.
    """
    # Włączenie rozszerzenia Spatial Analyst
    arcpy.CheckOutExtension("Spatial")

    # Wczytanie NMT (Numeryczny Model Terenu - sama ziemia)
    nmt = Raster(nmt_raster)
    
    # Ustawienie środowiska analizy (snapowanie do siatki rastra)
    arcpy.env.snapRaster = nmt
    arcpy.env.cellSize = nmt.meanCellWidth

    # 1. Analiza terenu (Slope - nachylenie, Aspect - ekspozycja stoku)
    slope = Slope(nmt, "DEGREE")
    aspect = Aspect(nmt)
    
    # Reklasyfikacja nachylenia: im stromiej, tym wyższy koszt (1, 2, 4, 8)
    slope_cost = Reclassify(
        slope,
        "VALUE",
        RemapRange([[0, 5, 1], [5, 15, 2], [15, 30, 4], [30, 90, 8]]),
    )

    # 2. Obsługa budynków - tworzenie strefy buforowej
    buildings_buffer = os.path.join(output_gdb, "buildings_buffer_10m")
    if arcpy.Exists(buildings_buffer):
        arcpy.management.Delete(buildings_buffer)

    # Bufor 10m wokół każdego budynku (strefa niebezpieczna)
    arcpy.analysis.Buffer(
        buildings_fc,
        buildings_buffer,
        "10 Meters",
        dissolve_option="ALL",
    )

    # Konwersja buforów (poligonów) na raster, aby można je było dodać do mapy kosztów
    buildings_raster = os.path.join(output_gdb, "buildings_r")
    if arcpy.Exists(buildings_raster):
        arcpy.management.Delete(buildings_raster)

    oid_field = arcpy.Describe(buildings_buffer).OIDFieldName
    arcpy.conversion.PolygonToRaster(
        buildings_buffer, oid_field, buildings_raster, cellsize=nmt.meanCellWidth
    )

    # 3. Wpływ wiatru (Algebra map)
    if wind_speed > 0:
        # Obliczamy różnicę między ekspozycją stoku (Aspect) a kierunkiem wiatru
        angle_diff = Abs(Mod(aspect - float(wind_deg) + 180.0, 360.0) - 180.0)
        # Formuła: wiatr wiejący prostopadle do zbocza zwiększa turbulencje
        wind_factor_raster = 1.0 + (float(wind_speed) / 15.0) * (angle_diff / 180.0)
        # Ograniczenie dolne współczynnika
        wind_factor_raster = Con(wind_factor_raster < 0.6, 0.6, wind_factor_raster)
        base_cost = slope_cost * wind_factor_raster
    else:
        base_cost = slope_cost
        
    # 4. Wpływ roślinności (NMPT - NMT = Wysokość obiektów/drzew)
    # NMPT (Model Pokrycia Terenu) zawiera korony drzew, NMT to grunt.
    vegetation = Raster(vegetation_raster)
    vegetation_height = Con(IsNull(vegetation), 0, vegetation - nmt)
    # Korekta błędów ujemnych (czasem zdarzają się szumy w danych)
    vegetation_height = Con(vegetation_height < 0, 0, vegetation_height)
    
    # Mnożnik kosztu rośnie wraz z wysokością roślinności
    vegetation_multiplier = 1.0 + (vegetation_height * float(vegetation_penalty))
    base_cost = base_cost * vegetation_multiplier

    # 5. Finalne sklejenie kosztów (Algebra warunkowa - Con)
    # Jeśli komórka pokrywa się z budynkiem (IsNull jest False), nałóż ogromną karę (penalty).
    # W przeciwnym razie użyj obliczonego kosztu bazowego.
    cost_raster = Con(
        IsNull(buildings_raster),
        base_cost,
        base_cost * float(penalty),
    )

    # Zapis wynikowego rastra kosztu na dysku
    cost_output = os.path.join(output_gdb, "cost_surface")
    cost_raster.save(cost_output)
    return cost_output


def create_3d_path(nmt_raster, path_2d, output_gdb, altitude_offset=0.0):
    """
    Konwertuje płaską trasę (2D) na linię trójwymiarową (3D), "przyklejając" ją do terenu.
    Dodatkowo podnosi trasę o zadaną wysokość przelotu (altitude_offset).
    """
    output_3d = os.path.join(output_gdb, "drone_path_3d")
    if arcpy.Exists(output_3d):
        arcpy.management.Delete(output_3d)

    # Zapamiętanie ustawień środowiska, aby je potem przywrócić
    prev_snap = arcpy.env.snapRaster
    prev_cell = arcpy.env.cellSize
    prev_extent = arcpy.env.extent
    
    try:
        arcpy.CheckOutExtension("3D")
        arcpy.CheckOutExtension("Spatial")
        nmt = Raster(nmt_raster)
        
        # Tymczasowa zmiana środowiska dla poprawności interpolacji
        with arcpy.EnvManager(
            snapRaster=nmt_raster,
            cellSize=nmt.meanCellWidth,
            extent=nmt.extent,
        ):
            # Jeśli zdefiniowano wysokość przelotu (np. 30m nad ziemią)
            if altitude_offset:
                temp_surface = os.path.join(output_gdb, "nmt_offset")
                if arcpy.Exists(temp_surface):
                    arcpy.management.Delete(temp_surface)
                
                # Dodajemy stałą wartość (np. 30) do każdej komórki NMT
                (nmt + float(altitude_offset)).save(temp_surface)
                
                # InterpolateShape tworzy geometrię 3D (Z-aware) na podstawie powierzchni
                arcpy.ddd.InterpolateShape(temp_surface, path_2d, output_3d)
                
                # Sprzątanie pliku tymczasowego
                if arcpy.Exists(temp_surface):
                    arcpy.management.Delete(temp_surface)
            else:
                # Trasa bezpośrednio na ziemi (0m AGL)
                arcpy.ddd.InterpolateShape(nmt_raster, path_2d, output_3d)
                
        return output_3d
    except Exception as exc:
        arcpy.AddWarning(f"Nie udało się utworzyć trasy 3D: {exc}")
        return None
    finally:
        # Przywrócenie ustawień środowiska
        arcpy.env.snapRaster = prev_snap
        arcpy.env.cellSize = prev_cell
        arcpy.env.extent = prev_extent


# ==========================================
# FUNKCJA STERUJĄCA (ORCHESTRATOR)
# ==========================================

def compute_path(
    workspace,
    nmt_raster,
    buildings_fc,
    output_gdb,
    start_xy,
    end_xy,
    api_key,
    penalty=1000,
    altitude_offset=30.0,
    vegetation_raster=None,
    vegetation_penalty=3.0,
    ):
    """
    Funkcja zarządzająca całym procesem:
    1. Pobiera pogodę.
    2. Buduje raster kosztów.
    3. Konwertuje współrzędne start/stop na punkty.
    4. Oblicza najtańszą trasę (CostDistance + CostPath).
    5. Generuje wersję 3D trasy.
    """
    arcpy.env.workspace = workspace
    arcpy.env.overwriteOutput = True # Pozwala nadpisywać pliki

    wind_speed, wind_deg = get_lublin_weather(api_key)
    arcpy.AddMessage(f"Warunki pogodowe - Wiatr: {wind_speed} m/s, Kierunek: {wind_deg}")

    # Tworzenie mapy trudności przelotu
    cost_surface = build_cost_raster(
        nmt_raster,
        buildings_fc,
        output_gdb,
        wind_speed,
        wind_deg,
        penalty,
        vegetation_raster,
        vegetation_penalty,
    )
    
    # Tworzenie punktów startowego i końcowego
    start_fc = create_point_fc(output_gdb, nmt_raster, "start_pt", start_xy)
    end_fc = create_point_fc(output_gdb, nmt_raster, "end_pt", end_xy)

    arcpy.CheckOutExtension("Spatial")

    # Obliczanie odległości kosztowej (mapa odległości od startu uwzględniająca trudność)
    cost_dist = os.path.join(output_gdb, "cost_distance")
    back_link = os.path.join(output_gdb, "back_link") # Raster kierunkowy potrzebny do wyznaczenia ścieżki
    
    cost_distance = CostDistance(start_fc, cost_surface, out_backlink_raster=back_link)
    cost_distance.save(cost_dist)

    output_path = os.path.join(output_gdb, "drone_path")
    if arcpy.Exists(output_path):
        arcpy.management.Delete(output_path)

    # Wyznaczenie najtańszej ścieżki (linii 2D) od punktu końcowego do startowego
    CostPathAsPolyline(end_fc, cost_dist, back_link, output_path)
    
    # Konwersja do 3D
    output_3d = create_3d_path(nmt_raster, output_path, output_gdb, altitude_offset)
    
    return output_3d or output_path


# ==========================================
# MAIN - WEJŚCIE DO PROGRAMU Z ARCGIS
# ==========================================

def main():
    # Pobieranie parametrów z interfejsu narzędzia ArcGIS Pro
    workspace = arcpy.GetParameterAsText(0)      # Folder roboczy
    nmt_raster = arcpy.GetParameterAsText(1)     # Raster wysokościowy (NMT)
    nmpt_raster = arcpy.GetParameterAsText(2)    # Raster pokrycia terenu (NMPT)
    buildings_fc = arcpy.GetParameterAsText(3)   # Warstwa budynków (wektorowa)
    output_gdb = arcpy.GetParameterAsText(4)     # Geobaza wyjściowa (.gdb)
    
    # Współrzędne w formacie tekstowym "X, Y" (np. "746025.26, 383566.23")
    start_xy_text = arcpy.GetParameterAsText(5) 
    end_xy_text = arcpy.GetParameterAsText(6)
    
    altitude_offset_text = arcpy.GetParameterAsText(7) # Wysokość lotu drona
    
    # Klucz API (dla bezpieczeństwa w produkcji powinien być w zmiennych środowiskowych)
    api_key = "1d490f98beea0754ca8a15bfc848c685"

    try:
        # Parsowanie współrzędnych tekstowych na liczby
        start_xy = parse_xy(start_xy_text)
        end_xy = parse_xy(end_xy_text)
        
        # Domyślna wysokość drona w metrach, jeśli użytkownik nie poda
        altitude_offset = float(altitude_offset_text) if altitude_offset_text else 30.0
        
        arcpy.AddMessage("Rozpoczynanie obliczeń trasy...")
        
        result = compute_path(
            workspace,
            nmt_raster,
            buildings_fc,
            output_gdb,
            start_xy,
            end_xy,
            api_key,
            altitude_offset=altitude_offset,
            vegetation_raster=nmpt_raster,
        )
        arcpy.AddMessage(f"Sukces! Wynik zapisany w: {result}")
        
    except ValueError as e:
        arcpy.AddError(f"Błąd danych wejściowych (sprawdź format współrzędnych): {e}")
    except Exception as e:
        arcpy.AddError(f"Wystąpił nieoczekiwany błąd: {e}")

if __name__ == "__main__":
    main()