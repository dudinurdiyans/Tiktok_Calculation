# SHO Cancellation Dashboard V3

Perbaikan V3 fokus pada bug periode dan total omzet.

## Penyebab bug sebelumnya

Tanggal pada raw Shopee dapat bersifat ambigu, misalnya `08/12/2026`.
Jika orientasi tanggal salah:
- 12 Agustus bisa dibaca 8 Desember
- periode L3M menjadi Oct | Nov | Dec
- hanya sebagian row masuk filter L3M
- Total Omzet ALL menjadi jauh lebih kecil

## Perbaikan

1. Parser tanggal Auto membandingkan:
   - DD/MM/YYYY
   - MM/DD/YYYY

2. Parser yang menghasilkan tanggal masa depan paling sedikit akan dipilih.

3. Row dengan `Waktu Pesanan Dibuat` di masa depan dibuang.

4. L3M mengambil 3 bulan yang benar-benar terdapat di dataset,
   bukan membuat bulan baru dari `pd.period_range(end=max_date)`.

5. Ada panel `Validasi Parsing Tanggal` yang menampilkan:
   - parser yang dipakai
   - tanggal minimum
   - tanggal maksimum
   - jumlah row future yang dibuang
   - jumlah row dan omzet per bulan

Untuk dataset Jun-Aug 2026, periode yang benar harus tampil:
`Jun 2026 | Jul 2026 | Aug 2026`.

## Run

```bash
pip install -r requirements.txt
streamlit run app.py
```
