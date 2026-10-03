"""Parsers for manually saved Rate Your Music HTML files.

The parser layer is deliberately side-effect free.  It never fetches RYM and it
never writes to the Music database; callers decide how parsed DTOs are staged
and committed.
"""

from __future__ import annotations

import json
import re
import unicodedata
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree

from bs4 import BeautifulSoup


PARSER_VERSION = "rym-html-4"
RYM_HOSTS = {"rateyourmusic.com", "www.rateyourmusic.com"}
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WORD_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def clean_text(value):
    return " ".join(str(value or "").replace("\xa0", " ").split()).strip()


def normalize_text(value):
    text = unicodedata.normalize("NFKC", clean_text(value)).casefold()
    text = text.replace("&", " and ").replace("’", "'")
    text = " ".join("".join(char if char.isalnum() else " " for char in text).split())
    return text


def normalize_rym_url(value):
    text = clean_text(value)
    if not text:
        return None
    if text.startswith("//"):
        text = f"https:{text}"
    parsed = urlparse(text)
    if parsed.netloc and parsed.netloc.lower() not in RYM_HOSTS:
        return text
    path = unquote(parsed.path or text.split("?", 1)[0]).rstrip("/") + "/"
    return f"https://rateyourmusic.com{path}"


def _build_rym_genre_hierarchy(occurrences):
    """Collapse a preorder hierarchy into canonical genres and DAG relations."""
    canonical = {}
    relations = set()
    stack = {}
    anomalies = 0
    for occurrence in occurrences:
        name = clean_text(occurrence.get("name"))
        url = normalize_rym_url(occurrence.get("url"))
        if not name or not url or "/genre/" not in url:
            continue
        depth = max(0, int(occurrence.get("depth") or 0))
        parent_url = stack.get(depth - 1) if depth else None
        if depth and not parent_url:
            anomalies += 1
        if parent_url and parent_url != url:
            relations.add((parent_url, url))
        stack[depth] = url
        for level in [level for level in stack if level > depth]:
            del stack[level]

        row = canonical.setdefault(url, {
            "name": name,
            "url": url,
            "slug": slug_from_genre_url(url),
            "description": "",
            "depth": depth,
            "parentUrls": set(),
        })
        row["depth"] = min(row["depth"], depth)
        description = clean_text(occurrence.get("description"))
        if len(description) > len(row["description"]):
            row["description"] = description
        if parent_url and parent_url != url:
            row["parentUrls"].add(parent_url)

    rows = []
    for row in canonical.values():
        rows.append({**row, "parentUrls": sorted(row["parentUrls"])})
    rows.sort(key=lambda row: (row["depth"], normalize_text(row["name"])))
    return {
        "pageType": "RYM_GENRE_HIERARCHY_DOCX",
        "source": "RYM",
        "rows": rows,
        "relations": [
            {"parentUrl": parent, "childUrl": child}
            for parent, child in sorted(relations)
        ],
        "occurrenceCount": len(occurrences),
        "anomalyCount": anomalies,
    }


def parse_rym_genre_docx(source_path):
    """Read RYM genre links and Word list levels without external dependencies."""
    path = Path(source_path)
    if not path.is_file() or path.suffix.casefold() != ".docx":
        raise ValueError("Wybierz istniejący plik DOCX")
    with zipfile.ZipFile(path) as archive:
        document = ElementTree.fromstring(archive.read("word/document.xml"))
        rels = ElementTree.fromstring(archive.read("word/_rels/document.xml.rels"))
    targets = {
        relation.get("Id"): relation.get("Target")
        for relation in rels.findall(f"{{{PACKAGE_REL_NS}}}Relationship")
    }
    occurrences = []
    pending = None
    w = f"{{{WORD_NS}}}"
    r_id = f"{{{WORD_REL_NS}}}id"
    for paragraph in document.findall(f".//{w}body//{w}p"):
        text = clean_text("".join(node.text or "" for node in paragraph.findall(f".//{w}t")))
        if not text:
            continue
        genre_url = None
        for hyperlink in paragraph.findall(f".//{w}hyperlink"):
            target = targets.get(hyperlink.get(r_id))
            if target and "/genre/" in target:
                genre_url = target
                break
        if genre_url:
            level = paragraph.find(f"./{w}pPr/{w}numPr/{w}ilvl")
            depth = int(level.get(f"{w}val") or 0) + 1 if level is not None else 0
            pending = {"name": text, "url": genre_url, "depth": depth, "description": ""}
            occurrences.append(pending)
        elif pending and not pending["description"]:
            pending["description"] = text
            pending = None
    result = _build_rym_genre_hierarchy(occurrences)
    result.update({"title": path.stem, "sourcePath": str(path), "parserVersion": PARSER_VERSION})
    return result


def slug_from_genre_url(value):
    parsed = urlparse(normalize_rym_url(value) or "")
    match = re.search(r"/genre/([^/]+)/", parsed.path, re.I)
    return unquote(match.group(1)).casefold() if match else None


def parse_number(value):
    text = clean_text(value).replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(match.group(0)) if match else None


def parse_int(value):
    number = parse_number(value)
    return int(number) if number is not None else None


def parse_year(value):
    match = re.search(r"(?<!\d)(1\d{3}|20\d{2}|2100)(?!\d)", clean_text(value))
    return int(match.group(1)) if match else None


def parse_duration(value):
    text = clean_text(value)
    if not text:
        return None
    parts = text.split(":")
    if not all(part.isdigit() for part in parts):
        return None
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + int(part)
    return seconds


def parse_release_date(value):
    text = clean_text(value)
    for pattern in ("%d %B %Y", "%B %d %Y", "%Y-%m-%d", "%Y"):
        try:
            date = datetime.strptime(text.replace(",", ""), pattern)
            return date.strftime("%Y-%m-%d") if pattern != "%Y" else None
        except ValueError:
            continue
    return None


def first_text(node, selector):
    found = node.select_one(selector) if node else None
    return clean_text(found.get_text(" ", strip=True)) if found else None


def unique_strings(values):
    result = []
    seen = set()
    for value in values:
        text = clean_text(value)
        key = normalize_text(text)
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def extract_genre_links(node, selector):
    return [
        {
            "name": clean_text(link.get_text(" ", strip=True)),
            "url": normalize_rym_url(link.get("href")),
            "slug": slug_from_genre_url(link.get("href")),
        }
        for link in node.select(f"{selector} a[href*='/genre/']")
        if clean_text(link.get_text(" ", strip=True))
    ]


def extract_media_ids(node):
    identifiers = []
    seen = set()
    for container in node.select("[data-links]"):
        try:
            links = json.loads(container.get("data-links") or "{}")
        except (TypeError, ValueError):
            continue
        for source, values in links.items():
            if not isinstance(values, dict):
                continue
            for external_value, details in values.items():
                key = (source.casefold(), str(external_value))
                if key in seen:
                    continue
                seen.add(key)
                identifiers.append({
                    "source": source.casefold(),
                    "type": str((details or {}).get("type") or "id"),
                    "value": str(external_value),
                    "url": (details or {}).get("url"),
                })
    return identifiers


def page_title(soup):
    return clean_text(soup.title.get_text(" ", strip=True)) if soup.title else ""


def source_url(soup):
    canonical = soup.select_one("link[rel~=canonical][href]")
    if canonical:
        return normalize_rym_url(canonical.get("href"))
    og = soup.select_one("meta[property='og:url'][content]")
    if og:
        return normalize_rym_url(og.get("content"))
    saved = soup.find(string=re.compile(r"saved from url=.*rateyourmusic\.com", re.I))
    if saved:
        match = re.search(r"https?://rateyourmusic\.com[^\s-]*", str(saved))
        if match:
            return normalize_rym_url(match.group(0))
    semantic = soup.select_one("meta[itemprop='url'][content]")
    return normalize_rym_url(semantic.get("content")) if semantic else None


class RYMPageDetector:
    @staticmethod
    def detect(soup):
        if soup.select_one("tr[id^='page_catalog_item_'] td.or_q_rating_date_s"):
            return "RYM_COLLECTION"
        if soup.select_one("#page_genre_index_section_hierarchy, .page_genre_index_hierarchy"):
            return "RYM_GENRE_INDEX"
        if soup.select_one(".page_charts_section_charts_item.object_release"):
            return "RYM_CHART"
        if soup.select_one(".release_page, #page_release, .album_title"):
            return "RYM_RELEASE"
        canonical = source_url(soup) or ""
        if "/charts/" in canonical:
            return "RYM_CHART"
        if "/release/" in canonical:
            return "RYM_RELEASE"
        raise ValueError("Nie rozpoznano typu zapisanej strony RYM")


class RYMCollectionParser:
    page_type = "RYM_COLLECTION"

    def parse(self, soup):
        rows = []
        for item in soup.select("tr[id^='page_catalog_item_']"):
            album = item.select_one("td.or_q_albumartist_td a.album[href]")
            if not album:
                continue
            position = len(rows) + 1
            rating_image = item.select_one("td.or_q_rating_date_s img[alt]")
            if not rating_image:
                raise ValueError(f"Brak oceny w wierszu kolekcji {position}")
            rating_match = re.fullmatch(r"([0-5](?:\.[0-9]+)?) stars?", rating_image.get("alt", ""), re.I)
            if not rating_match:
                raise ValueError(f"Brak oceny w wierszu kolekcji {position}")
            rating = float(rating_match.group(1))
            if not (0.5 <= rating <= 5.0 and rating * 2 == round(rating * 2)):
                raise ValueError(f"Nieprawidłowa ocena w wierszu kolekcji {position}")
            artist_links = item.select("td.or_q_albumartist_td a.artist")
            artists = unique_strings(link.get_text(" ", strip=True) for link in artist_links)
            if not artists:
                raise ValueError(f"Brak artysty w wierszu kolekcji {position}")
            release_url = normalize_rym_url(album.get("href"))
            release_type_match = re.search(r"/release/([^/]+)/", release_url or "")
            album_id_match = re.search(r"\[Album(\d+)\]", album.get("title") or "")
            if not release_url or not album_id_match:
                raise ValueError(f"Brak identyfikatora wydania w wierszu kolekcji {position}")
            year = parse_year(first_text(item, "td.or_q_albumartist_td .smallgray"))
            month = first_text(item, ".date_element_month")
            day = first_text(item, ".date_element_day")
            rated_year = first_text(item, ".date_element_year")
            try:
                rated_at = datetime.strptime(f"{month} {day} {rated_year}", "%b %d %Y").date().isoformat()
            except ValueError:
                rated_at = None
            rating_id_match = re.search(r"page_catalog_item_(\d+)", item.get("id") or "")
            rows.append({
                "position": position,
                "rymReleaseId": album_id_match.group(1),
                "releaseUrl": release_url,
                "title": clean_text(album.get_text(" ", strip=True)),
                "artists": artists,
                "artistCredit": " / ".join(artists),
                "releaseYear": year,
                "releaseType": (release_type_match.group(1).replace("-", " ").title() if release_type_match else "Album"),
                "userRating": rating,
                "ratedAt": rated_at,
                "rymRatingId": rating_id_match.group(1) if rating_id_match else None,
                "rymArtistIds": [re.search(r"\[Artist(\d+)\]", link.get("title") or "").group(1)
                                 if re.search(r"\[Artist(\d+)\]", link.get("title") or "") else None
                                 for link in artist_links],
                "ownership": first_text(item, ".or_q_ownership"),
                "tags": unique_strings(link.get_text(" ", strip=True) for link in item.select(".or_q_tagcloud a")),
                "coverSavedPath": (item.select_one(".or_q_thumb_album img") or {}).get("src"),
            })
        if not rows:
            raise ValueError("Strona kolekcji nie zawiera ocen")
        return {
            "pageType": self.page_type,
            "source": "RYM",
            "sourceUrl": source_url(soup),
            "title": page_title(soup),
            "rows": rows,
        }


class RYMGenreIndexParser:
    page_type = "RYM_GENRE_INDEX"

    @staticmethod
    def _genre(link, description=None, depth=0):
        return {
            "name": clean_text(link.get_text(" ", strip=True)),
            "url": normalize_rym_url(link.get("href")),
            "slug": slug_from_genre_url(link.get("href")),
            "description": clean_text(description),
            "depth": int(depth),
            "source": "RYM",
            "parentUrls": [],
        }

    def parse(self, soup):
        genres = {}
        relations = set()
        for root in soup.select(".page_genre_index_hierarchy_item"):
            root_link = root.select_one(
                ".page_genre_index_hierarchy_item_main_inner h2 a[href*='/genre/'], "
                ".page_genre_index_hierarchy_item_main h2 a[href*='/genre/']"
            )
            if not root_link:
                links = root.select("a[href*='/genre/']")
                root_link = next((link for link in links if clean_text(link.get_text(" ", strip=True))), None)
            if not root_link:
                continue
            root_description = first_text(root, ".page_genre_index_hierarchy_item_description")
            root_genre = self._genre(root_link, root_description, 0)
            genres[root_genre["url"]] = root_genre

            for child in root.select("li.hierarchy_list_item"):
                child_link = child.select_one(
                    ":scope > .hierarchy_list_item_details a[href*='/genre/'], "
                    ":scope > div a[href*='/genre/']"
                )
                if not child_link:
                    continue
                child_description = first_text(child, ":scope > .hierarchy_list_item_details p")
                parent_li = child.find_parent("li", class_="hierarchy_list_item")
                parent_url = root_genre["url"]
                depth = 1
                if parent_li and root in parent_li.parents:
                    parent_link = parent_li.select_one(
                        ":scope > .hierarchy_list_item_details a[href*='/genre/'], "
                        ":scope > div a[href*='/genre/']"
                    )
                    if parent_link:
                        parent_url = normalize_rym_url(parent_link.get("href"))
                    depth = len(child.find_parents("li", class_="hierarchy_list_item")) + 1
                child_genre = self._genre(child_link, child_description, depth)
                existing = genres.get(child_genre["url"])
                if existing:
                    if not existing.get("description") and child_genre.get("description"):
                        existing["description"] = child_genre["description"]
                    existing["depth"] = min(existing.get("depth", depth), depth)
                else:
                    genres[child_genre["url"]] = child_genre
                if parent_url and parent_url != child_genre["url"]:
                    relations.add((parent_url, child_genre["url"]))

        for parent_url, child_url in relations:
            if child_url in genres and parent_url not in genres[child_url]["parentUrls"]:
                genres[child_url]["parentUrls"].append(parent_url)
        return {
            "pageType": self.page_type,
            "source": "RYM",
            "sourceUrl": source_url(soup),
            "title": page_title(soup),
            "genres": list(genres.values()),
            "relations": [
                {"parentUrl": parent, "childUrl": child, "relationType": "SUBGENRE"}
                for parent, child in sorted(relations)
            ],
            "rows": list(genres.values()),
        }


class RYMChartParser:
    page_type = "RYM_CHART"

    @staticmethod
    def _cover(item):
        image = item.select_one(".page_charts_section_charts_item_image img")
        local = image.get("src") if image else None
        if local and (local.startswith("data:") or re.match(r"^https?://|^//", local, re.I)):
            local = None
        remote = image.get("data-src") if image else None
        for source in item.select(".page_charts_section_charts_item_image source[srcset], .page_charts_section_charts_item_image source[data-srcset]"):
            source_set = source.get("srcset") or source.get("data-srcset") or ""
            candidate = clean_text(source_set.split(",", 1)[0].strip().split(" ", 1)[0])
            if candidate:
                remote = f"https:{candidate}" if candidate.startswith("//") else candidate
                break
        if remote and remote.startswith("//"):
            remote = f"https:{remote}"
        return {"local": local, "remote": remote}

    def parse(self, soup):
        rows = []
        for position, item in enumerate(soup.select(".page_charts_section_charts_item.object_release"), 1):
            release_link = item.select_one("a.page_charts_section_charts_item_link.release[href]")
            if not release_link:
                continue
            release_url = normalize_rym_url(release_link.get("href"))
            title = first_text(release_link, ".ui_name_locale_original") or clean_text(release_link.get_text(" ", strip=True))
            artist_nodes = item.select(
                ".page_charts_section_charts_item_credited_links_primary a.artist, "
                ".page_charts_section_charts_item_credited_text a.artist"
            )
            artists = unique_strings(node.get_text(" ", strip=True) for node in artist_nodes)
            artist_credit = " / ".join(artists) or first_text(item, ".page_charts_section_charts_item_credited_text") or "Unknown Artist"
            date_text = (
                first_text(item, ".page_charts_section_charts_item_date > span:not(.page_charts_section_charts_item_release_type)")
                or first_text(item, ".page_charts_section_charts_item_date")
                or ""
            )
            year = parse_year(date_text)
            release_type = first_text(item, ".page_charts_section_charts_item_date .page_charts_section_charts_item_release_type")
            if not release_type:
                release_type = first_text(item, ".page_charts_section_charts_item_release_type") or "Album"
            release_id_match = re.search(r"(\d+)$", item.get("id") or "")
            rating_display = first_text(item, ".page_charts_section_charts_item_details_average_num")
            ratings_display = first_text(item, ".page_charts_section_charts_item_details_ratings .abbr")
            reviews_display = first_text(item, ".page_charts_section_charts_item_details_reviews .abbr")
            cover = self._cover(item)
            rows.append({
                "position": position,
                "rymReleaseId": release_id_match.group(1) if release_id_match else None,
                "releaseUrl": release_url,
                "title": title,
                "normalizedTitle": normalize_text(title),
                "artists": artists or [artist_credit],
                "artistCredit": artist_credit,
                "normalizedArtistCredit": normalize_text(artist_credit),
                "releaseDate": parse_release_date(date_text),
                "releaseYear": year,
                "releaseType": release_type,
                "primaryGenres": extract_genre_links(item, ".page_charts_section_charts_item_genres_primary"),
                "secondaryGenres": extract_genre_links(item, ".page_charts_section_charts_item_genres_secondary"),
                "descriptors": unique_strings(
                    node.get_text(" ", strip=True)
                    for node in item.select(".page_charts_section_charts_item_genre_descriptors .comma_separated")
                ),
                "rymRating": parse_number(rating_display),
                "rymRatingDisplay": rating_display,
                "rymRatingsDisplay": ratings_display,
                "rymRatingsApprox": parse_int(ratings_display) if ratings_display and not re.search(r"[kKmM]", ratings_display) else None,
                "rymReviewsDisplay": reviews_display,
                "rymReviews": parse_int(reviews_display),
                "coverLocal": cover["local"],
                "coverRemote": cover["remote"],
                "externalIds": extract_media_ids(item),
            })

        canonical = source_url(soup)
        parsed = urlparse(canonical or "")
        segments = [unquote(part) for part in parsed.path.split("/") if part]
        filters = {}
        if len(segments) >= 2 and segments[0] == "charts":
            filters["chartType"] = segments[1]
        if len(segments) >= 3:
            filters["releaseType"] = segments[2]
        if len(segments) >= 4:
            filters["timeRange"] = segments[3]
        filters["genres"] = [part[2:].replace("-", " ").title() for part in segments if part.startswith("g:")]
        title = re.sub(r"\s*-\s*Rate Your Music\s*$", "", page_title(soup), flags=re.I)
        return {
            "pageType": self.page_type,
            "source": "RYM",
            "sourceUrl": canonical,
            "title": title,
            "rankingKey": canonical or normalize_text(title),
            "filters": filters,
            "rows": rows,
        }


class RYMReleasePageParser:
    page_type = "RYM_RELEASE"

    @staticmethod
    def _info_rows(soup):
        result = {}
        table = soup.select_one(".section_main_info table.album_info") or soup.select_one("table.album_info")
        if not table:
            return result
        for row in table.select("tr"):
            head = first_text(row, "th.info_hdr")
            cell = row.select_one("td")
            if head and cell:
                result[head.casefold()] = clean_text(cell.get_text(" ", strip=True))
        return result

    @staticmethod
    def _tracks(soup):
        container = soup.select_one("#tracks_mobile") or soup.select_one("#tracks") or soup.select_one("ul.tracks.tracklisting")
        tracks = []
        if not container:
            return tracks
        for index, row in enumerate(container.select(":scope > li.track"), 1):
            position = first_text(row, ".tracklist_num") or str(index)
            title_node = row.select_one(".tracklist_title a.song") or row.select_one(".tracklist_title [itemprop='name']")
            title = clean_text(title_node.get_text(" ", strip=True)) if title_node else first_text(row, ".tracklist_title")
            duration_node = row.select_one(".tracklist_duration")
            duration = parse_int(duration_node.get("data-inseconds")) if duration_node else None
            if duration is None:
                duration = parse_duration(duration_node.get_text(" ", strip=True) if duration_node else None)
            if title:
                tracks.append({
                    "position": position,
                    "discNumber": None,
                    "title": title,
                    "normalizedTitle": normalize_text(title),
                    "durationSeconds": duration,
                    "source": "RYM",
                })
        return tracks

    @staticmethod
    def _credits(soup):
        container = soup.select_one("#credits_credits_mobile") or soup.select_one("#credits_credits") or soup.select_one(".section_credits ul.credits")
        credits = []
        if not container:
            return credits
        for row in container.select(":scope > li"):
            artist = row.select_one("a.artist")
            name = clean_text(artist.get_text(" ", strip=True)) if artist else ""
            roles = unique_strings(node.get_text(" ", strip=True) for node in row.select(".role_name"))
            if not name:
                role_keys = {normalize_text(role) for role in roles}
                name = next(
                    (
                        clean_text(value)
                        for value in row.stripped_strings
                        if clean_text(value) not in {",", "-"}
                        and normalize_text(value) not in role_keys
                    ),
                    "",
                )
            if name:
                credits.append({"name": name, "roles": roles})
        return credits

    def parse(self, soup):
        info = self._info_rows(soup)
        title_meta = soup.select_one(".section_main_info meta[itemprop='name'][content]") or soup.select_one("meta[itemprop='name'][content]")
        title = clean_text(title_meta.get("content")) if title_meta else None
        if not title:
            album_title = soup.select_one(".album_title")
            title = clean_text(next((str(node) for node in album_title.contents if getattr(node, "name", None) is None), "")) if album_title else None
        artist_nodes = soup.select(".section_main_info [itemprop='byArtist'] a.artist")
        if not artist_nodes:
            artist_nodes = soup.select(".album_title a.artist")[:1]
        artists = unique_strings(node.get_text(" ", strip=True) for node in artist_nodes)
        artist_credit = " / ".join(artists) or info.get("artist") or "Unknown Artist"
        release_id = None
        shortcut = soup.select_one("input.album_shortcut[value]")
        if shortcut:
            match = re.search(r"Album(\d+)", shortcut.get("value") or "", re.I)
            release_id = match.group(1) if match else None
        if not release_id:
            link = soup.select_one("a[href*='release_id=']")
            match = re.search(r"release_id=(\d+)", link.get("href") if link else "")
            release_id = match.group(1) if match else None
        released_text = info.get("released") or ""
        release_date = parse_release_date(released_text)
        year_match = re.search(r"\b(18|19|20)\d{2}\b", released_text)
        year = int(year_match.group(0)) if year_match else None
        rating_meta = soup.select_one("[itemprop='aggregateRating'] meta[itemprop='ratingValue'][content]")
        count_meta = soup.select_one("[itemprop='aggregateRating'] meta[itemprop='ratingCount'][content]")
        review_meta = soup.select_one("[itemprop='aggregateRating'] meta[itemprop='reviewCount'][content]")
        primary = extract_genre_links(soup, ".release_pri_genres")
        secondary = extract_genre_links(soup, ".release_sec_genres")
        descriptor_meta = soup.select("tr.release_descriptors meta[content]")
        descriptors = unique_strings(node.get("content") for node in descriptor_meta)
        if not descriptors:
            descriptor_text = first_text(soup, ".release_pri_descriptors") or ""
            descriptors = unique_strings(descriptor_text.split(","))
        cover = soup.select_one("[class*='coverart_'] img") or soup.select_one("img[alt^='Cover art for']")
        cover_local = cover.get("src") if cover else None
        cover_remote = None
        if cover:
            srcset = clean_text(cover.get("srcset"))
            if srcset:
                cover_remote = srcset.split(",", 1)[0].split(" ", 1)[0]
                if cover_remote.startswith("//"):
                    cover_remote = f"https:{cover_remote}"
        if not cover_remote:
            og_image = soup.select_one("meta[property='og:image'][content]")
            cover_remote = og_image.get("content") if og_image else None
        release_url = source_url(soup)
        label = catalog_number = None
        first_issue = next((issue for issue in soup.select(".issue_info") if issue.select_one("a.label")), None)
        if not first_issue:
            first_issue = soup.select_one(".issue_info")
        if first_issue:
            labels = first_issue.select("a.label")
            label = clean_text(labels[0].get_text(" ", strip=True)) if labels else None
            issue_text = clean_text(first_issue.get_text(" ", strip=True))
            catalog_match = re.search(r"/\s*([A-Z0-9][A-Z0-9._-]+)\b", issue_text, re.I)
            catalog_number = catalog_match.group(1) if catalog_match else None
        row = {
            "position": 1,
            "rymReleaseId": release_id,
            "releaseUrl": release_url,
            "title": title,
            "normalizedTitle": normalize_text(title),
            "artists": artists or [artist_credit],
            "artistCredit": artist_credit,
            "normalizedArtistCredit": normalize_text(artist_credit),
            "releaseDate": release_date,
            "releaseYear": year,
            "releaseType": info.get("type") or "Album",
            "recordedText": info.get("recorded"),
            "primaryGenres": primary,
            "secondaryGenres": secondary,
            "descriptors": descriptors,
            "rymRating": parse_number(rating_meta.get("content") if rating_meta else info.get("rym rating")),
            "rymRatingDisplay": rating_meta.get("content") if rating_meta else info.get("rym rating"),
            "rymRatingsDisplay": count_meta.get("content") if count_meta else None,
            "rymRatingsApprox": parse_int(count_meta.get("content")) if count_meta else None,
            "rymReviewsDisplay": review_meta.get("content") if review_meta else None,
            "rymReviews": parse_int(review_meta.get("content")) if review_meta else None,
            "rankingText": info.get("ranked"),
            "coverLocal": cover_local,
            "coverRemote": cover_remote,
            "label": label,
            "catalogNumber": catalog_number,
            "issuesText": clean_text(first_issue.get_text(" ", strip=True)) if first_issue else None,
            "tracks": self._tracks(soup),
            "credits": self._credits(soup),
            "externalIds": extract_media_ids(soup),
        }
        return {
            "pageType": self.page_type,
            "source": "RYM",
            "sourceUrl": release_url,
            "title": f"{artist_credit} — {title}",
            "rows": [row],
        }


def parse_rym_html(html):
    soup = BeautifulSoup(str(html or ""), "html.parser")
    page_type = RYMPageDetector.detect(soup)
    parser = {
        "RYM_COLLECTION": RYMCollectionParser,
        "RYM_GENRE_INDEX": RYMGenreIndexParser,
        "RYM_CHART": RYMChartParser,
        "RYM_RELEASE": RYMReleasePageParser,
    }[page_type]()
    result = parser.parse(soup)
    result["parserVersion"] = PARSER_VERSION
    return result
