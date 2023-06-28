from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import httpx
from bs4 import BeautifulSoup
import time
import concurrent.futures
from pydantic import BaseModel, Field, validator
from enum import Enum
import psutil
from typing import List, Dict, Optional
import cpuinfo
import multiprocessing

app = FastAPI()

origins = [
    "http://localhost:3000",
    "https://kikisan.pages.dev",
    "https://kikisan.site",
    "https://www.kikisan.site",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Metode(str, Enum):
    def __str__(self):
        return str(self.value)

    METODE = "threadhttpx"


class Hasil(BaseModel):
    keyword: str
    pages: int
    metode: Metode
    upload: List[int]
    download: List[int]
    internet: List[int]
    cpu_list: List[float]
    ram_list: List[float]
    time: float
    cpu_type: Optional[str] = None
    cpu_threads: Optional[int] = None
    # cpu_frequency_max: Optional[float] = None
    # cpu_max_percent: Optional[List] = None
    ram_total: Optional[str] = None
    ram_available: Optional[str] = None
    # ram_max_percent: Optional[float] = None
    jumlah_data: int
    hasil: Optional[List[Dict]] = None


class DataRequest(BaseModel):
    keyword: str
    pages: int = Field(..., gt=0)
    metode: Metode

    @validator("keyword")
    def validate_keyword(cls, keyword):
        if not keyword.strip():
            raise ValueError("Keyword tidak boleh kosong atau hanya berisi spasi")
        return keyword


# data_threadhttpx = []


@app.post("/threadhttpx")
def input_threadhttpx(request: Request, input: DataRequest):
    try:
        base_url = "https://www.tokopedia.com/search"
        headers = {"User-Agent": request.headers.get("User-Agent")}

        manager = multiprocessing.Manager()
        cpu_list = manager.list()  # List untuk menyimpan data pemantauan CPU
        ram_list = manager.list()  # List untuk menyimpan data pemantauan RAM
        upload_list = (
            manager.list()
        )  # List untuk menyimpan data pemantauan Internet Upload
        download_list = (
            manager.list()
        )  # List untuk menyimpan data pemantauan Internet Download
        internet_list = manager.list()  # List untuk menyimpan data pemantauan Internet

        monitor_process = multiprocessing.Process(
            target=monitoring,
            args=(cpu_list, ram_list, upload_list, download_list, internet_list),
        )
        monitor_process.start()

        start_time = time.time()
        hasil = main(base_url, headers, input.keyword, input.pages)
        end_time = time.time()

        monitor_process.terminate()

        internet_upload = list(upload_list)
        internet_download = list(download_list)
        internet = list(internet_list)

        cpu_info = cpuinfo.get_cpu_info()
        cpu_type = cpu_info["brand_raw"]
        cpu_threads = psutil.cpu_count(logical=True)
        cpu_list_data = list(cpu_list)

        ram = psutil.virtual_memory()
        ram_total = format_bytes(ram.total)  # Total RAM dalam bytes
        ram_available = format_bytes(ram.available)  # RAM yang tersedia dalam bytes
        ram_list_data = list(ram_list)

        data = {
            "keyword": input.keyword,
            "pages": input.pages,
            "metode": input.metode,
            "upload": internet_upload,
            "download": internet_download,
            "internet": internet,
            "time": end_time - start_time,
            "cpu_list": cpu_list_data,
            "ram_list": ram_list_data,
            "cpu_type": cpu_type,
            "cpu_threads": cpu_threads,
            "ram_total": ram_total,
            "ram_available": ram_available,
            "jumlah_data": len(hasil),
            "hasil": hasil,
        }
        # data_threadhttpx.append(data)
        return data
    except Exception as e:
        return e


def main(base_url, headers, keyword, pages):
    product_soup = []
    with httpx.Client() as session:
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [
                executor.submit(scrape, base_url, headers, keyword, page, session)
                for page in range(1, pages + 1)
            ]
            for future in concurrent.futures.as_completed(futures):
                soup_produk = future.result()
                if soup_produk:
                    product_soup.extend(soup_produk)

    tasks = []
    with httpx.Client() as session:
        with concurrent.futures.ThreadPoolExecutor() as executor:
            for i in product_soup:
                tasks.append(executor.submit(scrape_page, i, session, headers))

        combined_data = []
        for task in concurrent.futures.as_completed(tasks):
            array = task.result()
            if array:
                combined_data.append(array)
        return combined_data


def scrape(base_url, headers, keyword, page, session):
    params = {"q": keyword, "page": page}
    try_count = 0
    while try_count < 5:
        try:
            response = session.get(
                base_url, headers=headers, params=params, timeout=30.0
            )
            response.raise_for_status()
            soup_produk = []
            soup = BeautifulSoup(response.content, "html.parser")
            products_data = soup.find_all("div", {"class": "css-llwpbs"})
            for i in products_data:
                if i.find("a", {"class": "pcv3__info-content css-gwkf0u"}) is not None:
                    soup_produk.append(i)
            print(f"Berhasil scrape data dari halaman {page}.")
            return soup_produk
        except (httpx.ConnectTimeout, httpx.TimeoutException, httpx.HTTPError):
            try_count += 1
            print(f"Koneksi ke halaman {page} timeout. Mencoba lagi...")
    else:
        print(
            f"Gagal melakukan koneksi ke halaman {page} setelah mencoba beberapa kali."
        )
        return []


def scrape_page(soup, session, headers):
    with concurrent.futures.ThreadPoolExecutor() as executor:
        href = soup.find("a")["href"]
        link_parts = href.split("r=")
        r_part = link_parts[-1]
        link_part = r_part.split("&")
        r_part = link_part[0]
        new_link = f"{r_part.replace('%3A', ':').replace('%2F', '/')}"
        new_link = new_link.split("%3FextParam")[0]
        new_link = new_link.split("%3Fsrc")[0]
        new_link = new_link.split("?extParam")[0]
        tasks = []

        # Menambahkan tugas scraping data produk ke dalam daftar tasks
        product_task = executor.submit(data_product, soup, new_link, session, headers)
        tasks.append(product_task)

        # Menambahkan tugas scraping data toko ke dalam daftar tasks
        shop_task = executor.submit(
            data_shop, "/".join(new_link.split("/")[:-1]), session, headers
        )
        tasks.append(shop_task)

        # Mengumpulkan hasil scraping
        results = {}
        for future in concurrent.futures.as_completed(tasks):
            results.update(future.result())
        # results.update(executor.submit(data_product, soup, new_link, session, headers))
        return results


def data_product(soup_produk, product_link, session, headers):
    try_count = 0
    while try_count < 5:
        try:
            response = session.get(product_link, headers=headers, timeout=30.0)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, "html.parser")

            data_to_scrape = {
                "link_product": "",
                "product_name": ("h1", {"class": "css-1os9jjn"}),
                "product_price": ("div", {"class": "price"}),
                "product_terjual": (
                    "span",
                    {"class": "prd_label-integrity css-1duhs3e"},
                ),
                "product_rating": (
                    "span",
                    {"class": "prd_rating-average-text css-t70v7i"},
                ),
                "product_diskon": (
                    "div",
                    {"class": "prd_badge-product-discount css-1qtulwh"},
                ),
                "price_ori": (
                    "div",
                    {"class": "prd_label-product-slash-price css-1u1z2kp"},
                ),
                "product_items": ("div", {"class": "css-1b2d3hk"}),
                "product_detail": ("li", {"class": "css-bwcbiv"}),
                "product_keterangan": ("span", {"class": "css-168ydy0 eytdjj01"}),
            }

            results = {}

            for key, value in data_to_scrape.items():
                if key == "product_detail":
                    tag, attrs = value
                    elements = soup.find_all(tag, attrs)
                    results[key] = [element.text.strip() for element in elements]
                elif key == "product_items":
                    tag, attrs = value
                    elements = soup.find_all(tag, attrs)
                    if elements:
                        for key_element in elements:
                            items = key_element.find_all(
                                "div", {"class": "css-1y1bj62"}
                            )
                            kunci = (
                                key_element.find(
                                    "p", {"class": "css-x7tz35-unf-heading e1qvo2ff8"}
                                )
                                .text.strip()
                                .split(":")[0]
                            )
                            results[kunci] = [
                                item.text.strip()
                                for item in items
                                if item.text.strip()
                                != ".css-1y1bj62{padding:4px 2px;display:-webkit-inline-box;display:-webkit-inline-flex;display:-ms-inline-flexbox;display:inline-flex;}"
                            ]
                    else:
                        results[key] = None
                elif key == "link_product":
                    results[key] = product_link
                elif (
                    key == "product_terjual"
                    or key == "product_rating"
                    or key == "product_diskon"
                    or key == "price_ori"
                ):
                    tag, attrs = value
                    element = soup_produk.find(tag, attrs)
                    if element:
                        results[key] = element.text.strip()
                    else:
                        results[key] = None
                else:
                    tag, attrs = value
                    element = soup.find(tag, attrs)
                    if element:
                        text = element.get_text(
                            separator="<br>"
                        )  # Gunakan separator '\n' untuk menambahkan baris baru
                        results[key] = text.strip()
                    else:
                        results[key] = None
            print(f"Berhasil scrape data produk dari halaman {product_link}")
            return results

        except (httpx.ConnectTimeout, httpx.TimeoutException, httpx.HTTPError):
            try_count += 1
            print(f"Koneksi ke {product_link} timeout. Mencoba lagi...")
    else:
        print(
            f"Gagal melakukan koneksi ke {product_link} setelah mencoba beberapa kali."
        )
        return {}


def data_shop(shop_link, session, headers):
    try_count = 0
    while try_count < 5:
        try:
            response = session.get(shop_link, headers=headers, timeout=30.0)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, "html.parser")

            data_to_scrape = {
                "link_shop": "",
                "shop_name": ("h1", {"class": "css-1g675hl"}),
                "shop_status": ("span", {"data-testid": "shopSellerStatusHeader"}),
                "shop_location": ("span", {"data-testid": "shopLocationHeader"}),
                "shop_info": ("div", {"class": "css-6x4cyu e1wfhb0y1"}),
            }

            results = {}

            for key, value in data_to_scrape.items():
                if key == "link_shop":
                    results[key] = shop_link
                elif key == "shop_status":
                    tag, attrs = value
                    element = soup.find(tag, attrs)
                    time = soup.find("strong", {"class": "time"})
                    if time:
                        waktu = time.text.strip()
                        status = element.text.strip()
                        results[key] = status + " " + waktu
                    elif element:
                        results[key] = element.text.strip()
                    else:
                        results[key] = None
                elif key == "shop_info":
                    tag, attrs = value
                    elements = soup.find_all(tag, attrs)
                    key = ["rating_toko", "respon_toko", "open_toko"]
                    ket = soup.find_all(
                        "p", {"class": "css-1dzsr7-unf-heading e1qvo2ff8"}
                    )
                    i = 0
                    for item, keterangan in zip(elements, ket):
                        if item and keterangan:
                            results[key[i]] = (
                                item.text.replace("\u00b1", "").strip()
                                + " "
                                + keterangan.text.strip()
                            )
                        else:
                            results[key[i]] = None
                        i += 1
                else:
                    tag, attrs = value
                    element = soup.find(tag, attrs)
                    if element:
                        results[key] = element.text.strip()
                    else:
                        results[key] = None
            print(f"Berhasil scrape data toko dari halaman {shop_link}")
            return results

        except (httpx.ConnectTimeout, httpx.TimeoutException, httpx.HTTPError):
            try_count += 1
            print(f"Koneksi ke {shop_link} timeout. Mencoba lagi...")
    else:
        print(f"Gagal melakukan koneksi ke {shop_link} setelah mencoba beberapa kali.")
        return {}


def monitoring(cpu_list, ram_list, upload_list, download_list, internet_list):
    # Memperoleh penggunaan internet
    last_total, last_sent, last_received = get_network_usage()
    while True:  # Loop utama untuk monitoring
        # Memperoleh penggunaan CPU
        cpu_usage = get_cpu_usage()
        print("Penggunaan CPU:", cpu_usage, "%")
        cpu_list.append(cpu_usage)

        # Memperoleh penggunaan RAM
        ram_usage = get_ram_usage()
        print("Penggunaan RAM:", ram_usage, "%")
        ram_list.append(ram_usage)

        # Memperoleh penggunaan internet
        bytes_total, bytes_sent, bytes_received = get_network_usage()

        # Menghitung penggunaan internet
        upload = bytes_sent - last_sent
        download = bytes_received - last_received
        internet = bytes_total - last_total

        print("Penggunaan Internet ~ Upload:", format_bytes(upload))
        print("Penggunaan Internet ~ Download:", format_bytes(download))
        print("Penggunaan Internet:", format_bytes(internet))
        upload_list.append(upload)
        download_list.append(download)
        internet_list.append(internet)


# Fungsi untuk memperoleh penggunaan CPU
def get_cpu_usage():
    return psutil.cpu_percent(interval=1, percpu=True)


# Fungsi untuk memperoleh penggunaan RAM
def get_ram_usage():
    ram = psutil.virtual_memory()
    return ram.percent


# Fungsi untuk memperoleh penggunaan Internet
def get_network_usage():
    received = psutil.net_io_counters().bytes_recv
    sent = psutil.net_io_counters().bytes_sent
    total = received + sent
    return total, sent, received


def format_bytes(bytes):
    # Fungsi ini mengubah ukuran byte menjadi format yang lebih mudah dibaca
    sizes = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while bytes >= 1024 and i < len(sizes) - 1:
        bytes /= 1024
        i += 1
    return "{:.2f} {}".format(bytes, sizes[i])


# @app.get("/data")
# def ambil_data(
#     keyword: Optional[str] = None,
#     pages: Optional[int] = None,
#     status: Optional[Status] = None,
# ):
#     if status is not None or keyword is not None or pages is not None:
#         result_filter = []
#         for data in data_threadhttpx:
#             data = Hasil.parse_obj(data)
#             if (
#                 status == data.status
#                 and data.keyword == keyword
#                 and data.pages == pages
#             ):
#                 result_filter.append(data)
#     else:
#         result_filter = data_threadhttpx
#     return result_filter


# @app.put("/monitoring")
# def ambil_data(input: DataRequest):
#     for data in data_threadhttpx:
#         if (
#             data["status"] == "baru"
#             and data["keyword"] == input.keyword
#             and data["pages"] == input.pages
#         ):
#             cpu_info = cpuinfo.get_cpu_info()
#             cpu_type = cpu_info["brand_raw"]
#             print("Tipe CPU:", cpu_type)
#             cpu_threads = psutil.cpu_count(logical=True)
#             print("thread cpu", cpu_threads)

#             ram = psutil.virtual_memory()
#             ram_total = ram.total  # Total RAM dalam bytes
#             print("Total RAM:", ram_total)
#             ram_available = ram.available  # RAM yang tersedia dalam bytes
#             print("RAM Tersedia:", ram_available)

#             cpu_percent_max = []  # Highest CPU usage during execution
#             cpu_frequency_max = 0  # Highest frekuensi CPU usage during execution
#             ram_percent_max = 0  # Highest RAM usage during execution

#             interval = 0.1  # Interval for monitoring (seconds)
#             duration = data["time"]
#             num_intervals = int(duration / interval) + 1

#             for _ in range(num_intervals):
#                 cpu_frequency = psutil.cpu_freq().current
#                 print("frekuensi cpu", cpu_frequency)
#                 cpu_percent = psutil.cpu_percent(interval=interval, percpu=True)
#                 print("cpu", cpu_percent)
#                 # Informasi RAM
#                 ram_percent = psutil.virtual_memory().percent
#                 print("ram", ram_percent)

#                 if cpu_frequency > cpu_frequency_max:
#                     cpu_frequency_max = cpu_frequency

#                 if cpu_percent > cpu_percent_max:
#                     cpu_percent_max = cpu_percent

#                 if ram_percent > ram_percent_max:
#                     ram_percent_max = ram_percent

#             data["cpu_type"] = cpu_type
#             data["cpu_threads"] = cpu_threads
#             data["cpu_frequency_max"] = cpu_frequency_max
#             data["cpu_max_percent"] = cpu_percent_max
#             data["ram_total"] = format_bytes(ram_total)
#             data["ram_max_percent"] = ram_percent_max
#             data["ram_available"] = format_bytes(ram_available)
#             data["status"] = "lama"

#     return data_threadhttpx
