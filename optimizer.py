import math
import os

import arcpy

try:
    import requests
except Exception:
    requests = None


def parse_xy(value):
    parts = [p.strip() for p in value.split(",")]
    return float(parts[0]), float(parts[1])


def bearing_deg(start_xy, end_xy):
    dx = end_xy[0] - start_xy[0]
    dy = end_xy[1] - start_xy[1]
    angle = math.degrees(math.atan2(dx, dy))
    return (angle + 360.0) % 360.0


def wind_factor(wind_speed):
    return max(0.6, 1.0 + (wind_speed / 15.0))


def get_lublin_weather(api_key):
    if not api_key or requests is None:
        return 0.0, 0.0

    url = (
        "https://api.openweathermap.org/data/2.5/weather"
        f"?q=Lublin,PL&appid={api_key}"
    )
    data = requests.get(url, timeout=10).json()
    wind_speed = float(data.get("wind", {}).get("speed") or 0.0)
    wind_deg = float(data.get("wind", {}).get("deg") or 0.0)
    return wind_speed, wind_deg


def create_point_fc(output_gdb, surface_raster, name, point_xy):
    fc_path = os.path.join(output_gdb, name)
    if arcpy.Exists(fc_path):
        arcpy.management.Delete(fc_path)

    spatial_ref = arcpy.Describe(surface_raster).spatialReference
    arcpy.management.CreateFeatureclass(
        output_gdb, name, "POINT", spatial_reference=spatial_ref
    )
    arcpy.management.AddField(fc_path, "Name", "TEXT")
    with arcpy.da.InsertCursor(fc_path, ["SHAPE@", "Name"]) as cursor:
        point = arcpy.Point(point_xy[0], point_xy[1])
        cursor.insertRow([arcpy.PointGeometry(point, spatial_ref), name])
    return fc_path


def ensure_point_has_cost(cost_raster, point_xy, label):
    value = arcpy.management.GetCellValue(
        cost_raster, f"{point_xy[0]} {point_xy[1]}"
    ).getOutput(0)
    if value is None:
        raise ValueError(f"Punkt {label} ma brak danych w rastrze kosztu.")
    value_text = str(value).strip().lower()
    if value_text in ("nodata", "nan", "none"):
        raise ValueError(f"Punkt {label} ma brak danych w rastrze kosztu.")


def build_cost_raster(
    surface_raster, buildings_fc, output_gdb, weather_factor, penalty, building_buffer_m
):
    arcpy.CheckOutExtension("Spatial")
    from arcpy.sa import Con, IsNull, Raster, Reclassify, RemapRange, Slope

    surface = Raster(surface_raster)
    arcpy.env.snapRaster = surface
    arcpy.env.cellSize = surface.meanCellWidth
    arcpy.env.extent = surface

    slope = Slope(surface, "DEGREE")
    slope_cost = Reclassify(
        slope,
        "VALUE",
        RemapRange([[0, 5, 1], [5, 15, 2], [15, 30, 4], [30, 90, 8]]),
    )

    buildings_source = buildings_fc
    buffer_value = 0.0 if building_buffer_m is None else float(building_buffer_m)
    if buffer_value > 0:
        buffered_buildings = os.path.join(output_gdb, "buildings_buffer")
        if arcpy.Exists(buffered_buildings):
            arcpy.management.Delete(buffered_buildings)
        arcpy.analysis.Buffer(
            buildings_fc, buffered_buildings, f"{buffer_value} Meters"
        )
        buildings_source = buffered_buildings

    buildings_raster = os.path.join(output_gdb, "buildings_r")
    if arcpy.Exists(buildings_raster):
        arcpy.management.Delete(buildings_raster)

    oid_field = arcpy.Describe(buildings_source).OIDFieldName
    arcpy.conversion.PolygonToRaster(
        buildings_source, oid_field, buildings_raster, cellsize=surface.meanCellWidth
    )

    penalty_value = 1.0 if penalty is None else float(penalty)
    base_cost = slope_cost * weather_factor
    cost_raster = Con(
        IsNull(buildings_raster),
        base_cost,
        base_cost * penalty_value,
    )

    cost_output = os.path.join(output_gdb, "cost_surface")
    cost_raster.save(cost_output)
    return cost_output


def compute_path(
    workspace,
    nmt_raster,
    nmpt_raster,
    buildings_fc,
    output_gdb,
    start_xy,
    end_xy,
    api_key,
    penalty=1000,
    building_buffer_m=0,
    max_range_m=None,
    flight_altitude_m=20,
    create_3d=True,
    horizontal_factor="COS",
    vertical_factor=None,
    ):
    arcpy.env.workspace = workspace
    arcpy.env.overwriteOutput = True

    if penalty is None:
        penalty = 1000
    if building_buffer_m is None:
        building_buffer_m = 0
    if flight_altitude_m is None:
        flight_altitude_m = 0

    wind_speed, wind_deg = get_lublin_weather(api_key)
    weather_factor = wind_factor(wind_speed)

    cost_surface = build_cost_raster(
        nmpt_raster,
        buildings_fc,
        output_gdb,
        weather_factor,
        penalty,
        building_buffer_m,
    )
    ensure_point_has_cost(cost_surface, start_xy, "start")
    ensure_point_has_cost(cost_surface, end_xy, "end")
    start_fc = create_point_fc(output_gdb, nmpt_raster, "start_pt", start_xy)
    end_fc = create_point_fc(output_gdb, nmpt_raster, "end_pt", end_xy)

    arcpy.CheckOutExtension("Spatial")
    from arcpy.sa import CreateConstantRaster, PathDistance, CostPathAsPolyline

    wind_raster_path = os.path.join(output_gdb, "wind_direction")
    if arcpy.Exists(wind_raster_path):
        arcpy.management.Delete(wind_raster_path)
    wind_raster = CreateConstantRaster(
        wind_deg, "FLOAT", arcpy.env.cellSize, arcpy.env.extent
    )
    wind_raster.save(wind_raster_path)

    cost_dist = os.path.join(output_gdb, "cost_distance")
    back_link = os.path.join(output_gdb, "back_link")
    path_kwargs = {
        "in_source_data": start_fc,
        "in_cost_raster": cost_surface,
        "out_backlink_raster": back_link,
        "in_surface_raster": nmpt_raster,
        "in_horizontal_raster": wind_raster_path,
        "horizontal_factor": horizontal_factor,
    }
    if vertical_factor:
        path_kwargs["vertical_factor"] = vertical_factor

    cost_distance = PathDistance(**path_kwargs)
    cost_distance.save(cost_dist)

    output_path = os.path.join(output_gdb, "drone_path")
    if arcpy.Exists(output_path):
        arcpy.management.Delete(output_path)

    CostPathAsPolyline(end_fc, cost_dist, back_link, output_path)
    path_length = 0.0
    with arcpy.da.SearchCursor(output_path, ["SHAPE@LENGTH"]) as cursor:
        for row in cursor:
            if row[0] is None:
                continue
            path_length += float(row[0])
    if path_length <= 0:
        from arcpy.sa import CostDistance

        cost_distance_fallback = CostDistance(
            start_fc, cost_surface, out_backlink_raster=back_link
        )
        cost_distance_fallback.save(cost_dist)
        CostPathAsPolyline(end_fc, cost_dist, back_link, output_path)
        path_length = 0.0
        with arcpy.da.SearchCursor(output_path, ["SHAPE@LENGTH"]) as cursor:
            for row in cursor:
                if row[0] is None:
                    continue
                path_length += float(row[0])
        if path_length <= 0:
            raise ValueError(
                "Nie wyznaczono poprawnej trasy (długość = 0). "
                "Sprawdź, czy punkty start/koniec leżą na rastrze kosztu i "
                "nie są zablokowane przez bufor budynków lub NoData."
            )
    if max_range_m is not None:
        total_length = 0.0
        with arcpy.da.SearchCursor(output_path, ["SHAPE@LENGTH"]) as cursor:
            for row in cursor:
                if row[0] is None:
                    continue
                total_length += float(row[0])
        if total_length > float(max_range_m):
            raise ValueError(
                f"Wyznaczona trasa {total_length:.1f} m przekracza limit "
                f"{float(max_range_m):.1f} m."
            )

    output_path_3d = None
    if create_3d:
        arcpy.CheckOutExtension("3D")
        from arcpy.sa import Raster

        flight_surface = os.path.join(output_gdb, "flight_surface")
        flight_surface_raster = Raster(nmt_raster) + float(flight_altitude_m)
        if arcpy.Exists(flight_surface):
            arcpy.management.Delete(flight_surface)
        flight_surface_raster.save(flight_surface)

        output_path_3d = os.path.join(output_gdb, "drone_path_3d")
        if arcpy.Exists(output_path_3d):
            arcpy.management.Delete(output_path_3d)
        arcpy.ddd.InterpolateShape(flight_surface, output_path, output_path_3d)

    return output_path, output_path_3d


def main():
    # UZUPEŁNIJ ŚCIEŻKI I WSPÓŁRZĘDNE
    workspace = r"C:\Projekty\drone-path-optimizer\projekt_arcgis"
    nmt_raster = r"C:\Projekty\drone-path-optimizer\dane\nmt_czechow.tif"
    nmpt_raster = r"C:\Projekty\drone-path-optimizer\dane\nmpt_czechow.tif"
    buildings_fc = r"C:\Projekty\drone-path-optimizer\dane\budynki_czechow.shp"
    output_gdb = r"C:\Projekty\drone-path-optimizer\projekt_arcgis\drone_path_optimizer_project.gdb"
    start_xy = (746867, 382144)
    end_xy = (748056, 383929)
    api_key = "1d490f98beea0754ca8a15bfc848c685"
    building_buffer_m = 0
    max_range_m = 5000
    flight_altitude_m = 20

    result_2d, result_3d = compute_path(
        workspace,
        nmt_raster,
        nmpt_raster,
        buildings_fc,
        output_gdb,
        start_xy,
        end_xy,
        api_key,
        building_buffer_m=building_buffer_m,
        max_range_m=max_range_m,
        flight_altitude_m=flight_altitude_m,
    )
    arcpy.AddMessage(f"Wynik 2D zapisany: {result_2d}")
    if result_3d:
        arcpy.AddMessage(f"Wynik 3D zapisany: {result_3d}")


if __name__ == "__main__":
    main()