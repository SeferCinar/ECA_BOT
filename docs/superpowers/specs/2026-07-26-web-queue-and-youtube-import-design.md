# Web Kuyruğu ve YouTube Playlist İçe Aktarma Tasarımı

## Amaç

Web kontrol panelinden bekleyen şarkıların sırası değiştirilebilmeli, kuyruk
paneli giriş yapılmış tüm ekranlarda görünür kalmalı ve bir YouTube oynatma
listesinin öğeleri seçili kalıcı playlist kaydına aktarılabilmelidir.

## Kapsam ve kararlar

- Sıra değiştirme yalnızca `MusicPlayer.queue` içindeki bekleyen öğeleri
  değiştirir. `current` (şu an çalan şarkı) asla yer değiştirmez veya yeniden
  başlatılmaz.
- Kuyruk paneli masaüstünde ana içeriğin sağında yapışkan görünür; dar
  ekranlarda ana içeriğin altına iner. Giriş ekranı bu davranışın dışındadır.
- Arayüzde HTML5 sürükle-bırak kullanılır. Bırakma işleminden sonra yeni sıra
  tek bir API isteğiyle sunucuya gönderilir; sunucunun döndürdüğü gerçek sıra
  tekrar çizilir.
- YouTube içe aktarma, indirilen medya dosyalarını değil video sayfa URL'lerini
  kalıcı playlist'in `songs` alanına ekler. Mevcut `playlist_play` akışı bu
  URL'leri sıraya alıp stream olarak çalacaktır.
- Aynı URL (tam string eşitliği) seçili playlist'te mevcutsa atlanır. Kaynak
  oynatma listesindeki tekrarlar da ilk görülen öğeden sonra atlanır.
- İçe aktarma bir sınır koymadan kaynak oynatma listesinin erişilebilir tüm
  geçerli video öğelerini işler.

## Mimari

### Kuyruk sıralama

`MusicPlayer` bekleyen şarkı sözlüklerini bir `deque` içinde tutar. Yeni bir
`replace_queue` işlemi, istemcinin gönderdiği sıra anahtarlarını mevcut queue
öğelerine bire bir eşler ve yalnızca her öğe tam olarak bir kez verildiğinde
deque'i değiştirir. Böylece eksik, yinelenen veya eski istemci verisi 400 ile
reddedilir; oynayan öğe kapsam dışı kalır.

`MusicService.reorder_queue(...)` oyuncuyu alır, doğrulamayı çağırır ve güncel
state snapshot döndürür. Korunan API'de `POST /api/queue/reorder` endpoint'i
gövdesinde ordered queue item kimliklerini ve isteğe bağlı `guild_id`'yi alır.
Endpoint hata durumlarını mevcut `ServiceError` biçiminde döndürür.

Snapshot'taki her kuyruk öğesi, ekran için gösterilen alanlara ek olarak sadece
o queue örneğini temsil eden stabil bir `queue_id` içerir. Bu kimlik, aynı isim
ve URL'li iki şarkının da ayrı ayrı sıralanabilmesini sağlar; URL veya isim
doğrudan kimlik olarak kullanılmaz.

### Sürekli kuyruk arayüzü

`index.html` ana uygulama içeriğini `main-content` ve `queue-sidebar` olarak
iki bölüme ayırır. Mevcut kuyruk listesi sidebar'a taşınır; ayrı Kuyruk sekmesi
kaldırılır. CSS büyük ekranlarda sidebar'ı sticky ve kaydırılabilir yapar,
küçük ekranlarda tek sütuna düşürür. JavaScript mevcut WebSocket/poll state
güncellemesinde sidebar listesini yeniler, sürükleme olaylarında geçici DOM
sırasını üretir ve bırakıldığında reorder endpoint'ine yollar.

İstek başarısızsa kullanıcıya toast hata mesajı gösterilir ve API'den gelen
sonraki state ile görünüm yeniden eşitlenir. Yenileme sırasında sürükleme
aktifse yeni state uygulanmayarak kullanıcının bırakma hareketi korunur.

### YouTube playlist içe aktarma

`Downloader` içine, `yt-dlp`'nin metadata extraction yeteneğini kullanan bir
playlist metadata metodu eklenir. Bu metot indirme/stream URL çözümleme
yapmadan her geçerli öğe için kanonik `https://www.youtube.com/watch?v=<id>`
veya aracın sağladığı `webpage_url` değerini döndürür. Geçersiz, boş veya video
öğesi içermeyen kaynaklar servis katmanında anlamlı `ServiceError` kodlarına
dönüşür.

`MusicService.playlist_import_youtube(name, url)` hedef kayıtlı playlist'i
okur, importer sonucunu sırayla ele alır, var olan ve kaynak içi tekrarları
atlar, kayıt değiştiyse bir kez kaydeder. Cevap hedef playlist adı, güncel
şarkı listesi/sayısı, `added` ve `skipped` sayılarını içerir.

Korunan API endpoint'i `POST /api/playlists/{name}/import-youtube` olup
`url` gövdesini alır. Seçili playlist detayında URL giriş alanı ve İçe Aktar
düğmesi bulunur. Başarılı sonucu toast olarak "X eklendi, Y atlandı" biçiminde
gösterir ve playlist detayını yeniler.

## Hata davranışı

- Hedef playlist yoksa: `NOT_FOUND` / 404.
- URL boş veya HTTP(S) URL değilse: `INVALID_URL` / 400.
- yt-dlp kaynak listeyi okuyamazsa: `IMPORT_FAILED` / 502.
- Kaynak geçerli video içermiyorsa veya hiçbir yeni parça yoksa işlem başarılı
  olur; sırasıyla `added: 0` ve uygun `skipped` sayısı döner. Bu, idempotent
  tekrar importları hata olarak değerlendirmez.
- Reorder listesi mevcut sırayla bire bir eşleşmiyorsa: `INVALID_QUEUE_ORDER` /
  400; sıra değiştirilmez.

## Test stratejisi

- `MusicPlayer` testleri queue ID üretimi ve geçerli/geçersiz yeniden sıralama
  kurallarını, çalan şarkının etkilenmediğini doğrular.
- Servis/API testleri reorder endpoint'inin yetkilendirme, guild çözümleme ve
  hata dönüşlerini doğrular.
- Playlist import testleri yeni URL ekleme, mevcut/kaynak içi tekrarları
  atlama, boş sonuç, downloader hatası ve tek kaydetme davranışını kapsar.
- Arayüz kodu mevcut state/snapshot sözleşmesini kullanır; responsive sidebar
  ve sürükle-bırak davranışı birincil manuel tarayıcı doğrulamasında kontrol
  edilir.

## Kapsam dışı

- YouTube playlist içeriğini import sırasında indirmek.
- Discord slash komutlarından kuyruk yeniden sıralama veya YouTube importu.
- Playlist öğelerine başlık/thumbnail gibi kalıcı metadata eklemek.
