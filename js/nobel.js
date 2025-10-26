// js/nobel.js
//
// Modal z noblistami. Sort DESC po roku.
// Checkboxy zapisują się w localStorage.
// Licznik postępu (ile z ilu) aktualizuje się live.

const overlayEl   = document.getElementById('nobel-overlay');
const openBtn     = document.getElementById('nobel-open-btn');
const closeBtn    = document.getElementById('nobel-close-btn');
const gridEl      = document.getElementById('nobel-grid');
const progressEl  = document.getElementById('nobel-progress');

const LS_KEY = 'nobelChecklistV1';

// Dane (rok, autor, książka startowa)
const DATA_RAW = [
  {year:1901,author:"Sully Prudhomme",book:"Stances et Poèmes"},
  {year:1902,author:"Theodor Mommsen",book:"Historia Rzymu"},
  {year:1903,author:"Bjørnstjerne Bjørnson",book:"Synnøve Solbakken"},
  {year:1904,author:"Frédéric Mistral",book:"Mirèio"},
  {year:1904,author:"José Echegaray",book:"El gran Galeoto"},
  {year:1905,author:"Henryk Sienkiewicz",book:"Quo Vadis"},
  {year:1906,author:"Giosuè Carducci",book:"Odi barbare"},
  {year:1907,author:"Rudyard Kipling",book:"Kim"},
  {year:1908,author:"Rudolf Christoph Eucken",book:"Sens i wartość życia"},
  {year:1909,author:"Selma Lagerlöf",book:"Saga o Göście Berlingu"},
  {year:1910,author:"Paul Heyse",book:"L’Arrabbiata i inne nowele"},
  {year:1911,author:"Maurice Maeterlinck",book:"Niebieski ptak"},
  {year:1912,author:"Gerhart Hauptmann",book:"Tkacze"},
  {year:1913,author:"Rabindranath Tagore",book:"Gitanjali"},
  {year:1915,author:"Romain Rolland",book:"Jan Krzysztof"},
  {year:1916,author:"Verner von Heidenstam",book:"Karolinerzy Karola XII"},
  {year:1917,author:"Karl Adolph Gjellerup",book:"Pielgrzym Kamanita"},
  {year:1917,author:"Henrik Pontoppidan",book:"Szczęśliwy Per"},
  {year:1919,author:"Carl Spitteler",book:"Prometeusz i Epimeteusz"},
  {year:1920,author:"Knut Hamsun",book:"Głód"},
  {year:1921,author:"Anatole France",book:"Bogowie pragną krwi"},
  {year:1922,author:"Jacinto Benavente",book:"Interesy stworzone"},
  {year:1923,author:"William Butler Yeats",book:"The Tower"},
  {year:1924,author:"Władysław Reymont",book:"Chłopi"},
  {year:1925,author:"George Bernard Shaw",book:"Pygmalion"},
  {year:1926,author:"Grazia Deledda",book:"Trzciny na wietrze"},
  {year:1927,author:"Henri Bergson",book:"Ewolucja twórcza"},
  {year:1928,author:"Sigrid Undset",book:"Krystyna, córka Lavransa"},
  {year:1929,author:"Thomas Mann",book:"Buddenbrookowie"},
  {year:1930,author:"Sinclair Lewis",book:"Babbitt"},
  {year:1931,author:"Erik Axel Karlfeldt",book:"Pieśni Fridolina"},
  {year:1932,author:"John Galsworthy",book:"The Forsyte Saga"},
  {year:1933,author:"Iwan Bunin",book:"Życie Arsenjewa"},
  {year:1934,author:"Luigi Pirandello",book:"Jeden, nikt i sto tysięcy"},
  {year:1936,author:"Eugene O’Neill",book:"Long Day’s Journey into Night"},
  {year:1937,author:"Roger Martin du Gard",book:"Rodzina Thibault"},
  {year:1938,author:"Pearl S. Buck",book:"The Good Earth"},
  {year:1939,author:"Frans Eemil Sillanpää",book:"Silja"},
  {year:1944,author:"Johannes Vilhelm Jensen",book:"Długa podróż"},
  {year:1945,author:"Gabriela Mistral",book:"Desolación"},
  {year:1946,author:"Hermann Hesse",book:"Siddhartha"},
  {year:1947,author:"André Gide",book:"Fałszerze"},
  {year:1948,author:"T.S. Eliot",book:"The Waste Land"},
  {year:1949,author:"William Faulkner",book:"The Sound and the Fury"},
  {year:1950,author:"Bertrand Russell",book:"A History of Western Philosophy"},
  {year:1951,author:"Pär Lagerkvist",book:"Barabbas"},
  {year:1952,author:"François Mauriac",book:"Kłębek żmij"},
  {year:1953,author:"Winston Churchill",book:"The Second World War"},
  {year:1954,author:"Ernest Hemingway",book:"The Old Man and the Sea"},
  {year:1955,author:"Halldór Laxness",book:"Niezależni"},
  {year:1956,author:"Juan Ramón Jiménez",book:"Platero i ja"},
  {year:1957,author:"Albert Camus",book:"Obcy"},
  {year:1958,author:"Boris Pasternak",book:"Doktor Żywago"},
  {year:1959,author:"Salvatore Quasimodo",book:"I od razu wieczór"},
  {year:1960,author:"Saint-John Perse",book:"Anabaza"},
  {year:1961,author:"Ivo Andrić",book:"Most na Drinie"},
  {year:1962,author:"John Steinbeck",book:"The Grapes of Wrath"},
  {year:1963,author:"Giorgos Seferis",book:"Dziennik okrętowy"},
  {year:1964,author:"Jean-Paul Sartre",book:"Mdłości"},
  {year:1965,author:"Michaił Szołochow",book:"Cichy Don"},
  {year:1966,author:"S.Y. Agnon",book:"Tylko wczoraj"},
  {year:1966,author:"Nelly Sachs",book:"Ucieczka i przemiana"},
  {year:1967,author:"Miguel Ángel Asturias",book:"Pan Prezydent"},
  {year:1968,author:"Yasunari Kawabata",book:"Kraina śniegu"},
  {year:1969,author:"Samuel Beckett",book:"Molloy"},
  {year:1970,author:"Aleksandr Sołżenicyn",book:"Jeden dzień Iwana Denisowicza"},
  {year:1971,author:"Pablo Neruda",book:"Canto General"},
  {year:1972,author:"Heinrich Böll",book:"Utracona cześć Katarzyny Blum"},
  {year:1973,author:"Patrick White",book:"Voss"},
  {year:1974,author:"Eyvind Johnson",book:"Powrót do Itaki"},
  {year:1974,author:"Harry Martinson",book:"Aniara"},
  {year:1975,author:"Eugenio Montale",book:"Kości sepii"},
  {year:1976,author:"Saul Bellow",book:"Herzog"},
  {year:1977,author:"Vicente Aleixandre",book:"Cień raju"},
  {year:1978,author:"Isaac Bashevis Singer",book:"Sztukmistrz z Lublina"},
  {year:1979,author:"Odysseas Elytis",book:"To Axion Esti"},
  {year:1980,author:"Czesław Miłosz",book:"Zniewolony umysł"},
  {year:1981,author:"Elias Canetti",book:"Oślepienie"},
  {year:1982,author:"Gabriel García Márquez",book:"Sto lat samotności"},
  {year:1983,author:"William Golding",book:"Lord of the Flies"},
  {year:1984,author:"Jaroslav Seifert",book:"Wiersze wybrane"},
  {year:1985,author:"Claude Simon",book:"Droga Flandrii"},
  {year:1986,author:"Wole Soyinka",book:"Death and the King’s Horseman"},
  {year:1987,author:"Joseph Brodsky",book:"Wiersze wybrane"},
  {year:1988,author:"Naguib Mahfouz",book:"Pałacowe pragnienia"},
  {year:1989,author:"Camilo José Cela",book:"Ul"},
  {year:1990,author:"Octavio Paz",book:"Labirynt samotności"},
  {year:1991,author:"Nadine Gordimer",book:"July’s People"},
  {year:1992,author:"Derek Walcott",book:"Omeros"},
  {year:1993,author:"Toni Morrison",book:"Beloved"},
  {year:1994,author:"Kenzaburō Ōe",book:"Sprawa osobista"},
  {year:1995,author:"Seamus Heaney",book:"North"},
  {year:1996,author:"Wisława Szymborska",book:"Koniec i początek"},
  {year:1997,author:"Dario Fo",book:"Przypadkowa śmierć anarchisty"},
  {year:1998,author:"José Saramago",book:"Miasto ślepców"},
  {year:1999,author:"Günter Grass",book:"Blaszany bębenek"},
  {year:2000,author:"Gao Xingjian",book:"Góra duszy"},
  {year:2001,author:"V.S. Naipaul",book:"A House for Mr Biswas"},
  {year:2002,author:"Imre Kertész",book:"Los utracony"},
  {year:2003,author:"J.M. Coetzee",book:"Disgrace"},
  {year:2004,author:"Elfriede Jelinek",book:"Pianistka"},
  {year:2005,author:"Harold Pinter",book:"Betrayal"},
  {year:2006,author:"Orhan Pamuk",book:"Nazywam się Czerwień"},
  {year:2007,author:"Doris Lessing",book:"The Golden Notebook"},
  {year:2008,author:"J.M.G. Le Clézio",book:"Pustynia"},
  {year:2009,author:"Herta Müller",book:"Kraina zielonych śliwek"},
  {year:2010,author:"Mario Vargas Llosa",book:"Miasto i psy"},
  {year:2011,author:"Tomas Tranströmer",book:"Wiersze zebrane"},
  {year:2012,author:"Mo Yan",book:"Klan czerwonego sorgo"},
  {year:2013,author:"Alice Munro",book:"Runaway"},
  {year:2014,author:"Patrick Modiano",book:"Ulica ciemnych sklepików"},
  {year:2015,author:"Swietłana Aleksijewicz",book:"Czarnobylska modlitwa"},
  {year:2016,author:"Bob Dylan",book:"Chronicles: Volume One"},
  {year:2017,author:"Kazuo Ishiguro",book:"The Remains of the Day"},
  {year:2018,author:"Olga Tokarczuk",book:"Bieguni"},
  {year:2019,author:"Peter Handke",book:"Strach bramkarza przed jedenastką"},
  {year:2020,author:"Louise Glück",book:"The Wild Iris"},
  {year:2021,author:"Abdulrazak Gurnah",book:"Paradise"},
  {year:2022,author:"Annie Ernaux",book:"Lata"},
  {year:2023,author:"Jon Fosse",book:"Septologia"},
  {year:2024,author:"Han Kang",book:"Wegetarianka"},
  {year:2025,author:"László Krasznahorkai",book:"Szatańskie tango"}
];

// sort malejąco po roku
const DATA = [...DATA_RAW].sort((a,b) => b.year - a.year);


// ---------- localStorage helpers ----------

function loadState() {
    try {
        const raw = localStorage.getItem(LS_KEY);
        if (!raw) return {};
        return JSON.parse(raw);
    } catch(e) {
        return {};
    }
}

function saveState(state) {
    localStorage.setItem(LS_KEY, JSON.stringify(state));
}

function keyOf(item) {
    return `${item.year}-${item.author}-${item.book}`.toLowerCase();
}


// ---------- progress (X / Y) ----------

function calcProgress() {
    const st = loadState();
    const total = DATA.length;
    let done = 0;
    for (const item of DATA) {
        const k = keyOf(item);
        if (st[k]) done++;
    }
    return { done, total };
}

function renderProgress() {
    if (!progressEl) return;
    const {done, total} = calcProgress();
    progressEl.textContent = `${done} / ${total}`;
}


// ---------- render listy ----------

function renderGrid() {
    const state = loadState();
    gridEl.innerHTML = DATA.map(item => {
        const k = keyOf(item);
        const checked = state[k] ? 'checked' : '';
        return `
        <div class="nobel-card" data-key="${k}">
            <input
                class="nobel-check"
                type="checkbox"
                ${checked}
                aria-label="Zaliczone: ${item.author} – ${item.book}"
            />
            <div class="nobel-info">
                <div class="nobel-author">${item.author}</div>
                <div class="nobel-book">${item.book}</div>
                <div class="nobel-year">${item.year}</div>
            </div>
        </div>`;
    }).join('');
}


// ---------- interakcje ----------

function bindChecklistHandlers() {
    gridEl.addEventListener('change', e => {
        const box = e.target;
        if (!box.classList.contains('nobel-check')) return;

        const card = box.closest('.nobel-card');
        if (!card) return;

        const k = card.getAttribute('data-key');
        const st = loadState();

        if (box.checked) {
            st[k] = true;
        } else {
            delete st[k];
        }
        saveState(st);
        renderProgress();
    });
}

function bindModalButtons() {
    if (openBtn) {
        openBtn.addEventListener('click', (e) => {
            e.preventDefault();
            overlayEl.hidden = false;
        });
    }

    // zamykanie klikając w tło albo w X
    if (overlayEl) {
        overlayEl.addEventListener('click', (e) => {
            const isBackdrop = e.target === overlayEl;
            const isCloseBtn = e.target.id === 'nobel-close-btn' || e.target.closest?.('#nobel-close-btn');
            if (isBackdrop || isCloseBtn) {
                overlayEl.hidden = true;
            }
        });
    }

    // Esc zamyka
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !overlayEl.hidden) {
            overlayEl.hidden = true;
        }
    });
}


// ---------- init ----------

function initNobel() {
    renderGrid();
    bindChecklistHandlers();
    bindModalButtons();
    renderProgress();
}

document.addEventListener('DOMContentLoaded', initNobel);
