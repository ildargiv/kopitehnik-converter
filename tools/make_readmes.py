"""Writes the short translated READMEs (README.<lang>.md); README.md (English) and README.ru.md are maintained by hand."""
from pathlib import Path

NAV = ("**Languages:** [English](README.md) · [Русский](README.ru.md) · [Deutsch](README.de.md) · "
       "[Español](README.es.md) · [Français](README.fr.md) · [Português](README.pt.md) · "
       "[Türkçe](README.tr.md) · [中文](README.zh.md)")
RELEASES = "https://github.com/ildargiv/kopitehnik-converter/releases/latest"

T = {
    "de": ("KopiTehnik Konverter",
           "Kostenlose Windows-Software für Fotolabore und Druckereien: Stapelkonvertierung, Farbkorrektur, Druckbögen, Zuschnitt mit der Maus, PDF-Editor mit Scan-Erkennung und Druck mit Vorschau. Bedienbar per Hand oder durch einen KI-Agenten.",
           ["Beliebige Eingaben: JPG, PNG, WebP, TIFF, HEIC, PSD, PDF, SVG, ZIP, Word, PowerPoint, Excel.",
            "Farbe: Auto-Korrektur, Weißabgleich, Helligkeit, Kontrast, Sättigung, Einzelfarben, ICC-Profil nach sRGB.",
            "Druckbogen: 10×15 und 9×12 auf A4, Passbilder, Kontaktbogen, Schnittmarken, Beschriftungen.",
            "Zuschnitt mit der Maus, Neigung ±45°, Drehen, Spiegeln, Rückgängig und Wiederholen.",
            "PDF-Editor: Text einfügen, ändern und verschieben, Scans lokal erkennen (Russisch und Englisch, ohne Cloud) und als Word oder Excel speichern.",
            "MCP-Server: KI-Agenten (Claude, Hermes, Cursor und andere) steuern alle Funktionen als Werkzeuge."],
           "Installation", "Installer herunterladen", "Die Oberfläche gibt es in 8 Sprachen; die Windows-Sprache wird erkannt, Standard ist Englisch. Der Programmname wird mitübersetzt.",
           "Die vollständige Dokumentation steht im englischen [README](README.md)."),
    "es": ("KopiTehnik Conversor",
           "Software gratuita para Windows para laboratorios fotográficos e imprentas: conversión por lotes, corrección de color, hojas de impresión, recorte con el ratón, editor de PDF con reconocimiento de escaneos e impresión con vista previa. Se maneja a mano o con un agente de IA.",
           ["Cualquier entrada: JPG, PNG, WebP, TIFF, HEIC, PSD, PDF, SVG, ZIP, Word, PowerPoint, Excel.",
            "Color: autocorrección, balance de blancos, brillo, contraste, saturación, colores por separado, perfil ICC a sRGB.",
            "Hoja de impresión: 10×15 y 9×12 en A4, fotos de documento, hoja de contactos, marcas de corte, pies de foto.",
            "Recorte con el ratón, inclinación ±45°, giro, espejo, deshacer y rehacer.",
            "Editor de PDF: insertar, corregir y mover texto, reconocer escaneos en local (ruso e inglés, sin nube) y guardar en Word o Excel.",
            "Servidor MCP: agentes de IA (Claude, Hermes, Cursor y otros) usan todas las funciones como herramientas."],
           "Instalación", "Descargar el instalador", "La interfaz está en 8 idiomas; se detecta el idioma de Windows y el predeterminado es inglés. El nombre del programa también se traduce.",
           "La documentación completa está en el [README](README.md) en inglés."),
    "fr": ("KopiTehnik Convertisseur",
           "Logiciel Windows gratuit pour laboratoires photo et imprimeries : conversion par lots, correction des couleurs, planches d'impression, recadrage à la souris, éditeur PDF avec reconnaissance de scans et impression avec aperçu. Piloté à la main ou par un agent IA.",
           ["Tous les formats : JPG, PNG, WebP, TIFF, HEIC, PSD, PDF, SVG, ZIP, Word, PowerPoint, Excel.",
            "Couleur : correction auto, balance des blancs, luminosité, contraste, saturation, couleurs séparées, profil ICC vers sRGB.",
            "Planche d'impression : 10×15 et 9×12 sur A4, photos d'identité, planche-contact, traits de coupe, légendes.",
            "Recadrage à la souris, inclinaison ±45°, rotation, miroir, annuler et rétablir.",
            "Éditeur PDF : insérer, corriger et déplacer du texte, reconnaître les scans en local (russe et anglais, sans cloud), enregistrer en Word ou Excel.",
            "Serveur MCP : les agents IA (Claude, Hermes, Cursor et autres) utilisent toutes les fonctions comme outils."],
           "Installation", "Télécharger l'installateur", "L'interface existe en 8 langues ; la langue de Windows est détectée, l'anglais est la langue par défaut. Le nom du programme est traduit aussi.",
           "La documentation complète se trouve dans le [README](README.md) en anglais."),
    "pt": ("KopiTehnik Conversor",
           "Software gratuito para Windows para laboratórios fotográficos e gráficas: conversão em lote, correção de cor, folhas de impressão, recorte com o rato, editor de PDF com reconhecimento de digitalizações e impressão com pré-visualização. Usado à mão ou por um agente de IA.",
           ["Qualquer entrada: JPG, PNG, WebP, TIFF, HEIC, PSD, PDF, SVG, ZIP, Word, PowerPoint, Excel.",
            "Cor: correção automática, balanço de brancos, brilho, contraste, saturação, cores separadas, perfil ICC para sRGB.",
            "Folha de impressão: 10×15 e 9×12 em A4, fotos de documento, folha de contactos, marcas de corte, legendas.",
            "Recorte com o rato, inclinação ±45°, rotação, espelho, desfazer e refazer.",
            "Editor de PDF: inserir, corrigir e mover texto, reconhecer digitalizações localmente (russo e inglês, sem nuvem) e guardar em Word ou Excel.",
            "Servidor MCP: agentes de IA (Claude, Hermes, Cursor e outros) usam todas as funções como ferramentas."],
           "Instalação", "Baixar o instalador", "A interface está em 8 idiomas; o idioma do Windows é detetado e o padrão é inglês. O nome do programa também é traduzido.",
           "A documentação completa está no [README](README.md) em inglês."),
    "tr": ("KopiTehnik Dönüştürücü",
           "Fotoğraf laboratuvarları ve matbaalar için ücretsiz Windows yazılımı: toplu dönüştürme, renk düzeltme, baskı sayfaları, fareyle kırpma, tarama tanımalı PDF düzenleyici ve önizlemeli yazdırma. Elle ya da bir yapay zekâ ajanıyla kullanılır.",
           ["Her girdi: JPG, PNG, WebP, TIFF, HEIC, PSD, PDF, SVG, ZIP, Word, PowerPoint, Excel.",
            "Renk: otomatik düzeltme, beyaz dengesi, parlaklık, kontrast, doygunluk, tek tek renkler, ICC profilinden sRGB'ye.",
            "Baskı sayfası: A4'te 10×15 ve 9×12, vesikalık fotoğraflar, kontak sayfası, kesim işaretleri, altyazılar.",
            "Fareyle kırpma, ±45° eğim, döndürme, aynalama, geri alma ve yineleme.",
            "PDF düzenleyici: metin ekleme, düzeltme ve taşıma, taramaları yerelde tanıma (Rusça ve İngilizce, bulutsuz), Word veya Excel olarak kaydetme.",
            "MCP sunucusu: yapay zekâ ajanları (Claude, Hermes, Cursor ve diğerleri) tüm işlevleri araç olarak kullanır."],
           "Kurulum", "Kurulum dosyasını indir", "Arayüz 8 dildedir; Windows dili otomatik algılanır, varsayılan İngilizcedir. Program adı da çevrilir.",
           "Tam belgeler İngilizce [README](README.md) dosyasındadır."),
    "zh": ("KopiTehnik 转换器",
           "面向照片冲印店和印刷店的免费 Windows 软件：批量转换、色彩校正、印刷版面、鼠标裁剪、带扫描件识别的 PDF 编辑器，以及带预览的打印。可手动操作，也可由 AI 代理操作。",
           ["支持多种输入：JPG、PNG、WebP、TIFF、HEIC、PSD、PDF、SVG、ZIP、Word、PowerPoint、Excel。",
            "色彩：自动校正、白平衡、亮度、对比度、饱和度、分色调整，ICC 配置文件转 sRGB。",
            "印刷版面：A4 上排 10×15 和 9×12、证件照、联系表、裁切标记、图注。",
            "鼠标裁剪、±45° 倾斜、旋转、镜像、撤销与重做。",
            "PDF 编辑器：插入、修改和移动文字，本地识别扫描件（俄语和英语，无需云端），可保存为 Word 或 Excel。",
            "MCP 服务器：AI 代理（Claude、Hermes、Cursor 等）可把所有功能当作工具使用。"],
           "安装", "下载安装程序", "界面支持 8 种语言，自动识别 Windows 语言，默认英语，程序名称也会随之翻译。",
           "完整文档见英文 [README](README.md)。"),
}

for code, (name, tagline, bullets, h_install, dl, note, more) in T.items():
    body = [f"# {name}", "", NAV, "", f"**{tagline}**", ""]
    body += [f"- {b}" for b in bullets]
    body += ["", f"## {h_install}", f"**[{dl}: KopiTehnik-Converter-Setup.exe]({RELEASES})**", "", note, "", more, "",
             "AGPL-3.0 · Ildar Gaisin · https://vk.ru/icc_profil", ""]
    Path(__file__).resolve().parent.parent.joinpath(f"README.{code}.md").write_text("\n".join(body), encoding="utf-8")
print("ok")
