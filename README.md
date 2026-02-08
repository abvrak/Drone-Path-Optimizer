# Drone Path Optimizer

**Optymalizator trasy przelotu drona** — narzędzie geoprzestrzenne do wyznaczania optymalnej ścieżki lotu bezzałogowego statku powietrznego (BSP) z uwzględnieniem rzeźby terenu, zabudowy, roślinności oraz aktualnych warunków wiatrowych.

Projekt zrealizowany jako narzędzie (Script Tool) dla środowiska **ArcGIS Pro** z wykorzystaniem biblioteki **ArcPy** oraz rozszerzeń **Spatial Analyst** i **3D Analyst**.

---

## 📋 Spis treści

1. [Opis projektu](#-opis-projektu)
2. [Obszar badań](#-obszar-badań)
3. [Dane wejściowe](#-dane-wejściowe)
4. [Architektura rozwiązania](#-architektura-rozwiązania)
5. [Algorytm wyznaczania trasy](#-algorytm-wyznaczania-trasy)
6. [Parametry narzędzia](#-parametry-narzędzia)
7. [Wymagania systemowe](#-wymagania-systemowe)
8. [Instalacja i uruchomienie](#-instalacja-i-uruchomienie)
9. [Struktura projektu](#-struktura-projektu)
10. [Przykład użycia](#-przykład-użycia)
11. [Ograniczenia](#-ograniczenia)
12. [Autor](#-autor)

---

## 📖 Opis projektu

Celem projektu jest opracowanie narzędzia GIS, które automatycznie wyznacza optymalną trasę przelotu drona pomiędzy dwoma punktami na terenie zurbanizowanym. Optymalizacja trasy uwzględnia następujące czynniki:

- **Rzeźba terenu** - nachylenie i ekspozycja stoków na podstawie Numerycznego Modelu Terenu (NMT)
- **Zabudowa** - budynki wraz ze strefami buforowymi (10 m) stanowią przeszkody o wysokim koszcie przelotu
- **Roślinność** - wysokość pokrycia roślinnego obliczana jako różnica NMPT i NMT zwiększa koszt przelotu
- **Warunki wiatrowe** - aktualne dane meteorologiczne pobierane w czasie rzeczywistym z API OpenWeatherMap wpływają na koszt przelotu w zależności od siły i kierunku wiatru
- **Wysokość lotu** - generacja trasy trójwymiarowej (3D) z uwzględnieniem zadanej wysokości nad terenem

Wynikiem działania narzędzia jest trasa 3D (linia Z-aware) zapisana w geobazie plikowej, którą można zwizualizować w widoku sceny 3D w ArcGIS Pro.

---

## 🗺️ Obszar badań

Obszarem badawczym jest dzielnica **Czechów** w **Lublinie** (województwo lubelskie, Polska).

| Parametr | Wartość |
|---|---|
| Lokalizacja | Czechów, Lublin, Polska |
| Układ współrzędnych | ETRF2000-PL / CS92 (EPSG:2180) |
| Jednostka | Metr |
| Odwzorowanie | Gauss-Krüger (Transverse Mercator) |

---

## 📂 Dane wejściowe

Projekt korzysta z trzech głównych zbiorów danych przestrzennych:

### 1. Numeryczny Model Terenu (NMT)
- **Plik:** `dane/nmt_czechow.tif`
- **Opis:** Raster przedstawiający wysokości bezwzględne powierzchni gruntu (bez budynków i roślinności)
- **Zastosowanie:** Analiza nachylenia, ekspozycji, generacja trasy 3D
- **Format:** GeoTIFF z plikiem georeferencji `.tfw`

### 2. Numeryczny Model Pokrycia Terenu (NMPT)
- **Plik:** `dane/nmpt_czechow.tif`
- **Opis:** Raster przedstawiający wysokości bezwzględne z uwzględnieniem budynków, drzew i innej roślinności
- **Zastosowanie:** Obliczanie wysokości roślinności (NMPT − NMT) jako dodatkowy czynnik kosztu
- **Format:** GeoTIFF z plikiem georeferencji `.tfw`

### 3. Warstwa budynków
- **Plik:** `dane/budynki_czechow.shp` (Shapefile)
- **Opis:** Wektorowa warstwa poligonowa z obrysami budynków na analizowanym obszarze
- **Zastosowanie:** Generacja stref buforowych (10 m) wokół budynków — obszary o wysokiej karze kosztowej
- **Format:** ESRI Shapefile (.shp, .dbf, .shx, .prj, .sbn, .sbx, .cpg)

### 4. Dane meteorologiczne (pobierane automatycznie)
- **Źródło:** [OpenWeatherMap API](https://openweathermap.org/api)
- **Lokalizacja:** Lublin, PL
- **Parametry:** Prędkość wiatru (m/s), kierunek wiatru (°)
- **Zastosowanie:** Dynamiczna modyfikacja kosztu przelotu na podstawie siły i kierunku wiatru

---

## 🏗️ Architektura rozwiązania

```
┌────────────────────────────────────────────────────────────────┐
│                    DANE WEJŚCIOWE                              │
│  ┌──────────┐  ┌──────────┐  ┌───────────┐  ┌──────────────┐   │
│  │   NMT    │  │   NMPT   │  │ Budynki   │  │ OpenWeather  │   │
│  │ (raster) │  │ (raster) │  │ (wektor)  │  │    API       │   │
│  └────┬─────┘  └────┬─────┘  └─────┬─────┘  └──────┬───────┘   │
│       │              │              │               │          │
│       ▼              ▼              ▼               ▼          │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              BUDOWA RASTRA KOSZTÓW                      │   │
│  │  ┌──────────────┐  ┌────────────────┐  ┌────────────┐   │   │
│  │  │  Nachylenie  │  │ Strefy buforowe│  │  Mnożnik   │   │   │
│  │  │  + Ekspozycja│  │  budynków 10m  │  │  wiatrowy  │   │   │
│  │  └──────┬───────┘  └───────┬────────┘  └─────┬──────┘   │   │
│  │         │                  │                 │          │   │
│  │         │    ┌─────────────────────┐         │          │   │
│  │         │    │ Wysokość roślinności│         │          │   │
│  │         │    │    (NMPT − NMT)     │         │          │   │
│  │         │    └─────────┬───────────┘         │          │   │
│  │         │              │                     │          │   │
│  │         ▼              ▼                     ▼          │   │
│  │  ┌─────────────────────────────────────────────────┐    │   │
│  │  │        RASTER KOSZTU (Cost Surface)             │    │   │
│  │  └────────────────────┬────────────────────────────┘    │   │
│  └───────────────────────┼─────────────────────────────────┘   │
│                          │                                     │
│                          ▼                                     │
│  ┌───────────────────────────────────────────────────────┐     │
│  │            WYZNACZANIE TRASY OPTYMALNEJ               │     │
│  │  Cost Distance ──► Back Link ──► Cost Path as Polyline│     │
│  └───────────────────────┬───────────────────────────────┘     │
│                          │                                     │
│                          ▼                                     │
│  ┌───────────────────────────────────────────────────────┐     │
│  │              GENERACJA TRASY 3D                       │     │
│  │  NMT + offset wysokości ──► InterpolateShape          │     │
│  └───────────────────────┬───────────────────────────────┘     │
│                          │                                     │
│                          ▼                                     │
│                  TRASA 3D (.gdb)                               │
└────────────────────────────────────────────────────────────────┘
```

---

## ⚙️ Algorytm wyznaczania trasy

Proces wyznaczania optymalnej trasy przelotu drona składa się z pięciu etapów:

### Etap 1 — Pobranie danych meteorologicznych
Skrypt łączy się z API OpenWeatherMap i pobiera aktualną prędkość (m/s) oraz kierunek (°) wiatru dla Lublina. Dane te są wykorzystywane w dalszych obliczeniach do modyfikacji kosztu przelotu.

### Etap 2 — Budowa rastra kosztów (Cost Surface)
Na raster kosztów składają się cztery komponenty:

| Komponent | Opis | Metoda |
|---|---|---|
| **Nachylenie terenu** | Im większe nachylenie, tym wyższy koszt przelotu | Reklasyfikacja: 0–5° → 1, 5–15° → 2, 15–30° → 4, 30–90° → 8 |
| **Strefy budynków** | Budynki z buforem 10 m stanowią obszary o bardzo wysokim koszcie | Mnożnik kary (domyślnie ×1000) na rastrze budynków |
| **Wpływ wiatru** | Wiatr przeciwny zwiększa koszt przelotu | Heurystyczny mnożnik oparty na różnicy kąta ekspozycji i kierunku wiatru |
| **Roślinność** | Wysoka roślinność (drzewa) utrudnia przelot | Wysokość roślinności (NMPT − NMT) × współczynnik kary (domyślnie ×3) |

Formuła końcowa kosztu komórki:

$$
C = \begin{cases}
S \cdot W \cdot V \cdot P & \text{jeśli komórka pokrywa się z budynkiem} \\
S \cdot W \cdot V & \text{w przeciwnym razie}
\end{cases}
$$

gdzie:
- $S$ — koszt wynikający z nachylenia terenu (1, 2, 4 lub 8)
- $W$ — mnożnik wiatrowy: $\max\left(0{,}6;\; 1 + \frac{v_w}{15} \cdot \frac{\Delta\alpha}{180}\right)$
- $V$ — mnożnik roślinności: $1 + h_r \cdot p_r$ ($h_r$ — wysokość roślinności, $p_r$ — współczynnik kary)
- $P$ — kara za budynki (domyślnie 1000)

### Etap 3 — Analiza kosztowa (Cost Distance)
Na podstawie rastra kosztów i punktu startowego obliczana jest mapa **odległości kosztowej** (Cost Distance) oraz raster **powiązań wstecznych** (Back Link). Mapa odległości kosztowej przypisuje każdej komórce skumulowany koszt dotarcia od punktu startowego.

### Etap 4 — Wyznaczenie najkrótszej ścieżki (Cost Path)
Funkcja `CostPathAsPolyline` wyznacza najkrótszą (najtańszą) ścieżkę od punktu końcowego do startowego, śledząc rastrowe powiązania wsteczne. Wynikiem jest linia 2D (polyline).

### Etap 5 — Konwersja do 3D
Trasa 2D jest konwertowana na geometrię trójwymiarową (Z-aware) za pomocą narzędzia `InterpolateShape`. Do powierzchni NMT dodawana jest zadana wysokość przelotu (domyślnie 30 m nad terenem), co pozwala na realistyczną wizualizację trasy lotu w widoku sceny 3D.

---

## 🎛️ Parametry narzędzia

Narzędzie przyjmuje parametry za pośrednictwem interfejsu ArcGIS Pro (Script Tool):

| Nr | Parametr | Typ | Opis | Przykład |
|---|---|---|---|---|
| 0 | Folder roboczy | Folder (Workspace) | Katalog roboczy projektu | `C:\Projekty\Drone-Path-Optimizer` |
| 1 | NMT | Raster Dataset | Numeryczny Model Terenu | `dane/nmt_czechow.tif` |
| 2 | NMPT | Raster Dataset | Numeryczny Model Pokrycia Terenu | `dane/nmpt_czechow.tif` |
| 3 | Budynki | Feature Class | Wektorowa warstwa budynków (poligony) | `dane/budynki_czechow.shp` |
| 4 | Geobaza wyjściowa | Workspace (.gdb) | Geobaza do zapisu wyników | `projekt_arcgis/drone_path_optimizer_project.gdb` |
| 5 | Punkt startowy | String | Współrzędne startu w formacie `X, Y` | `747945.82, 383931.63` |
| 6 | Punkt końcowy | String | Współrzędne celu w formacie `X, Y` | `746025.26, 383566.23` |
| 7 | Wysokość lotu | String (opcjonalny) | Wysokość lotu nad terenem w metrach | `30` (domyślnie 30 m) |

> **Uwaga:** Współrzędne należy podawać w układzie ETRF2000-PL / CS92 (EPSG:2180).

---

## 💻 Wymagania systemowe

### Oprogramowanie
| Wymaganie | Wersja |
|---|---|
| ArcGIS Pro | 3.x lub nowsza |
| Python | 3.9+ |
| Rozszerzenie Spatial Analyst | Wymagane (licencja) |
| Rozszerzenie 3D Analyst | Wymagane (licencja) |

### Biblioteki Python
| Biblioteka | Opis | Źródło |
|---|---|---|
| `arcpy` | Biblioteka geoprzestrzenna ArcGIS | Wbudowana w ArcGIS Pro |
| `requests` | Klient HTTP do komunikacji z API | `pip install requests` |
| `math` | Operacje matematyczne | Biblioteka standardowa Python |
| `os` | Obsługa systemu plików | Biblioteka standardowa Python |

### Dostęp sieciowy
- Wymagane połączenie z Internetem do pobierania danych pogodowych z OpenWeatherMap API
- W przypadku braku połączenia narzędzie działa poprawnie — przyjmuje wiatr 0 m/s

---

## 🚀 Instalacja i uruchomienie

### Krok 1 — Klonowanie repozytorium
```bash
git clone https://github.com/abvrak/Drone-Path-Optimizer.git
```

### Krok 2 — Otwarcie projektu w ArcGIS Pro
1. Uruchom **ArcGIS Pro**
2. Otwórz plik projektu: `projekt_arcgis/drone_path_optimizer_project.aprx`

### Krok 3 — Dodanie narzędzia (Script Tool)
Jeśli narzędzie nie jest jeszcze skonfigurowane w Toolbox:

1. W panelu **Catalog** kliknij prawym przyciskiem na plik `drone_path_optimizer_project.atbx`
2. Wybierz **New → Script**
3. W polu **Script File** wskaż ścieżkę do `optimizer.py`
4. Skonfiguruj parametry zgodnie z tabelą w sekcji [Parametry narzędzia](#-parametry-narzędzia)

### Krok 4 — Uruchomienie narzędzia
1. W panelu **Catalog** rozwiń Toolbox i kliknij dwukrotnie na narzędzie
2. Wypełnij wszystkie parametry:
   - Wskaż folder roboczy, rastry NMT i NMPT, warstwę budynków oraz geobazę wyjściową
   - Podaj współrzędne punktu startowego i końcowego w formacie `X, Y`
   - Opcjonalnie zmień wysokość lotu (domyślnie 30 m)
3. Kliknij **Run**

### Krok 5 — Wizualizacja wyniku
1. Wynikowa trasa (`drone_path_3d`) zostanie automatycznie zapisana w geobazie wyjściowej
2. Aby zobaczyć trasę w 3D:
   - Kliknij **Insert → New Map → New Local Scene**
   - Przeciągnij warstwę `drone_path_3d` na scenę
   - Dodaj raster NMT jako powierzchnię terenu (Ground Surface)

---

## 📁 Struktura projektu

```
Drone-Path-Optimizer/
│
├── README.md                          # Dokumentacja projektu (ten plik)
├── optimizer.py                       # Główny skrypt optymalizatora trasy
│
├── dane/                              # Dane wejściowe (źródłowe dane przestrzenne)
│   ├── nmt_czechow.tif                # Numeryczny Model Terenu (raster)
│   ├── nmt_czechow.tfw                # Plik georeferencji dla NMT
│   ├── nmt_czechow.tif.aux.xml        # Metadane pomocnicze NMT
│   ├── nmt_czechow.tif.ovr            # Piramidy (podgląd rastra) NMT
│   ├── nmpt_czechow.tif               # Numeryczny Model Pokrycia Terenu (raster)
│   ├── nmpt_czechow.tfw               # Plik georeferencji dla NMPT
│   ├── nmpt_czechow.tif.aux.xml       # Metadane pomocnicze NMPT
│   ├── nmpt_czechow.tif.ovr           # Piramidy (podgląd rastra) NMPT
│   ├── budynki_czechow.shp            # Warstwa budynków (Shapefile — geometria)
│   ├── budynki_czechow.dbf            # Atrybuty budynków
│   ├── budynki_czechow.shx            # Indeks przestrzenny
│   ├── budynki_czechow.prj            # Definicja układu współrzędnych
│   ├── budynki_czechow.sbn            # Indeks przestrzenny (binarne drzewo)
│   ├── budynki_czechow.sbx            # Indeks przestrzenny (pomocniczy)
│   └── budynki_czechow.cpg            # Strona kodowa atrybutów
│
└── projekt_arcgis/                    # Projekt ArcGIS Pro
    ├── drone_path_optimizer_project.aprx   # Plik projektu ArcGIS Pro
    ├── drone_path_optimizer_project.atbx   # Toolbox z narzędziem
    └── drone_path_optimizer_project.gdb/   # Geobaza plikowa (wyniki analiz)
```

---

## 📌 Przykład użycia

**Scenariusz:** Wyznaczenie trasy przelotu drona z osiedla na Czechowie do punktu docelowego po drugiej stronie dzielnicy, z wysokością lotu 30 m nad terenem.

**Parametry wejściowe:**
- Punkt startowy: `747945.82, 383931.63`
- Punkt końcowy: `746025.26, 383566.23`
- Wysokość lotu: `30` m
- NMT: `dane/nmt_czechow.tif`
- NMPT: `dane/nmpt_czechow.tif`
- Budynki: `dane/budynki_czechow.shp`

**Wyniki zapisane w geobazie:**

| Warstwa | Opis |
|---|---|
| `cost_surface` | Raster kosztu przelotu |
| `cost_distance` | Mapa skumulowanego kosztu od punktu startowego |
| `back_link` | Raster kierunkowy (powiązania wsteczne) |
| `start_pt` | Punkt startowy (Feature Class) |
| `end_pt` | Punkt końcowy (Feature Class) |
| `drone_path` | Wyznaczona trasa 2D (polilinia) |
| `drone_path_3d` | Wyznaczona trasa 3D (polilinia Z-aware) |
| `buildings_buffer_10m` | Strefy buforowe wokół budynków |

---

## ⚠️ Ograniczenia

- Narzędzie wymaga licencji **Spatial Analyst** i **3D Analyst** w ArcGIS Pro
- Dane pogodowe dotyczą ogólnie miasta Lublin - nie uwzględniają lokalnych mikroklimatów
- Raster kosztów nie uwzględnia dynamicznych przeszkód (inne drony, ptaki, tymczasowe strefy zakazu lotów)
- Współrzędne muszą być podawane w układzie **ETRF2000-PL / CS92** (EPSG:2180)
- Algorytm operuje na rastrze 2D - trasa 3D jest generowana post hoc przez interpolację na powierzchni terenu
- Narzędzie nie uwzględnia przepisów prawnych dotyczących stref lotniczych (CTR, ATZ itp.)

---

## 🛠️ Technologie

| Technologia | Zastosowanie |
|---|---|
| ![Python](https://img.shields.io/badge/Python-3.9+-3776AB?logo=python&logoColor=white) | Język programowania |
| ![ArcGIS Pro](https://img.shields.io/badge/ArcGIS%20Pro-3.x-2C7AC3?logo=esri&logoColor=white) | Platforma GIS |
| ![ArcPy](https://img.shields.io/badge/ArcPy-Spatial%20Analyst-purple) | Analiza przestrzenna |
| ![OpenWeatherMap](https://img.shields.io/badge/OpenWeatherMap-API-orange?logo=openweathermap) | Dane pogodowe w czasie rzeczywistym |

---

## 👤 Autorzy

- Adrian Burak
- Kamil Kapusta

---
