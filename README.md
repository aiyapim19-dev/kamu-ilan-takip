# Kamu İlan Takip

Kamu personel alım ilanı sitelerini **saatte bir** kontrol eder, yeni ilan çıkınca kurum adıyla telefonuna bildirim gönderir. Telefonda uygulama gibi kurulan bir sayfada ilanları (yeniler kırmızı çerçeveli) gösterir.

Kontrol edilen kaynaklar: Kamu İlan (SBB), Yerel Yönetimler (ÇŞB), ilan.gov.tr, Kariyer Kapısı, İŞKUR (memur + işçi), Resmî Gazete.

## Nasıl çalışır
- **GitHub Actions** her saat `scraper/scrape.py`'yi çalıştırır (ücretsiz, bilgisayarın açık olması gerekmez).
- Yeni ilanlar `docs/data/ilanlar.json`'a yazılır, **ntfy** uygulaması üzerinden telefona bildirim gider.
- **GitHub Pages** `docs/` klasörünü yayınlar; bu sayfa telefona uygulama olarak kurulur.

## Kurulum (yaklaşık 10 dakika)

1. **GitHub hesabı** aç (yoksa) ve yeni bir **public** depo oluştur (ör. `kamu-ilan-takip`). Pages'in ücretsiz olması için public gerekir; içindeki veri zaten herkese açık ilanlardır.
2. Bu klasörün **tüm içeriğini** depoya yükle. `.github` klasörü gizli olduğu için tarayıcıdan sürükle-bırak bazen atlar; **GitHub Desktop** veya `git push` kullan. Yüklendikten sonra depoda `.github/workflows/tara.yml` dosyasını görmelisin.
3. Depoda **Settings → Pages → Build and deployment**: Source = *Deploy from a branch*, Branch = `main`, klasör = `/docs` → Save. Birkaç dakika sonra adresin görünür: `https://KULLANICI.github.io/kamu-ilan-takip/`
4. **Telefona bildirim için:** telefona **ntfy** uygulamasını kur (App Store / Play Store) → "+" → tahmin edilmesi zor bir konu adı yaz (ör. `kamu-ilan-x7k2q9m4`) → Subscribe.
5. Depoda **Settings → Secrets and variables → Actions**:
   - *Secrets* sekmesi → **New repository secret**: Ad `NTFY_TOPIC`, değer: 4. adımdaki konu adı.
   - *Variables* sekmesi → **New repository variable**: Ad `APP_URL`, değer: 3. adımdaki Pages adresin (bildirime dokununca uygulama açılır).
6. **Actions** sekmesi → "Ilanlari tara" → **Run workflow**. İlk çalıştırma mevcut ilanları listeye alır ama bildirim göndermez (yoksa yüzlerce bildirim gelirdi). Sonraki saatlik çalışmalarda sadece yeni çıkanlar bildirilir.
7. **Uygulamayı kur:** telefonda Pages adresini aç. Android Chrome: sayfadaki "Kur" düğmesi veya ⋮ → *Uygulamayı yükle*. iPhone Safari: Paylaş → *Ana Ekrana Ekle*.

## Bilmen gerekenler (dürüst notlar)
- **Siteleri bu ortamdan test edemedim** (dış siteler kapalıydı). Çıkarma mantığını örnek HTML ile test ettim ama gerçek sayfa yapıları farklı olabilir. 6. adımdaki ilk çalıştırmadan sonra uygulamada **"Kaynak durumu"** bölümüne bak: yeşil = ilan bulundu, sarı/kırmızı = sorun var ve nedeni yazıyor. Sorunlu kaynağı bana söylersen o siteye özel ayar yaparım.
- **Kariyer Kapısı** ilanları e-Devlet girişi arkasında olabilir; bu durumda 0 ilan görünür. `ilan.gov.tr` ve Kariyer Kapısı JavaScript ile yüklendiği için tarayıcı motoruyla (Playwright) açılır.
- Resmî Gazete, `robots.txt` ile otomatik erişimi yasaklıyorsa betik **saygı gösterip atlar** (durumda görünür). Atama kararları için Resmî Gazete'nin kendi mobil uygulamasının bildirimlerini kullanabilirsin.
- Bildirim kontrolü **saatte bir**dir; GitHub zamanlayıcısı yoğunlukta birkaç dakika geç çalışabilir. Depoda 60 gün hiç etkinlik olmazsa GitHub zamanlamayı durdurup e-posta atabilir; Actions sekmesinden tekrar açarsın.
- Bildirim filtresi anahtar kelimelerle çalışır (alım, personel, memur, işçi, sözleşmeli, zabıta, öğretim vb.); `scraper/scrape.py` başındaki `INCLUDE` / `EXCLUDE` listelerinden düzenlenebilir. Kaynaklar `scraper/sources.json`'dadır.
- Konu adını (`NTFY_TOPIC`) kimseyle paylaşma; bilen herkes o konuya bildirim gönderebilir/okuyabilir.
