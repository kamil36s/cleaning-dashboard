const entry = (local_date, title, reconstructed_text, gated_sections = []) => ({
  local_date,
  timezone: "Europe/Warsaw",
  title,
  label: "AI-reconstructed diary entry",
  privacy_level: gated_sections.some((section) => section.privacy_level === "third_party_sensitive")
    ? "third_party_sensitive"
    : gated_sections.some((section) => section.privacy_level === "sensitive")
      ? "sensitive"
      : "private",
  base_privacy_level: "private",
  reconstructed_text,
  gated_sections,
});

const gated = (privacy_level, text, heading = null) => ({ privacy_level, heading, text });

// These are editorial reconstructions, not generated claim graphs. The build script
// attaches the complete user-message bundle for each Warsaw-local day and rejects
// dates, conversation IDs or message IDs that do not resolve to that bundle.
export const journalV2Entries = [
  entry(
    "2023-01-10",
    "Trzeba to wreszcie ułożyć",
    `Szukam nowej pracy w QA i znowu stoję w miejscu na etapie CV oraz wysyłania aplikacji. Mam rok doświadczenia jako Test Analyst: testy manualne, scenariusze, defekty, raportowanie. Nie chcę robić z tego napuszonej historii o wielkim specjaliście, ale też nie mogę opisać siebie tak, jakbym nic nie umiał. Patrzę na ofertę e-commerce, choć nie mam doświadczenia ani w e-commerce, ani w Agile. Wiem za to, że chcę ruszyć dalej i uczyć się automatyzacji.

Rozpisuję BDD, TDD, ATDD, ISTQB, książki i kursy. W obecnej pracy praktycznie nie rozwijam umiejętności, więc próbuję zbudować naukę obok niej. Do rozmów dochodzi Jira. Chcę mieć gotowy tracker firm, wersji CV, kontaktów, wysłanych zgłoszeń, odpowiedzi i kolejnych kroków. Oczywiście linki do gotowych rozwiązań okazują się martwe, więc wracam do pytania, jak zbudować to samemu.

Przerabiam CV zdanie po zdaniu. Opis obowiązków ma pokazać testy manualne i realną odpowiedzialność, ale bez chwalenia się jak z generatora korporacyjnych sloganów. Pytam, czy w ogóle jestem kandydatem do roli e-commerce, skoro nie pracowałem wcześniej w tym sektorze. Chcę uczciwie zaznaczyć, że automatyzacji dopiero się uczę, a nie udawać gotowego automatyka. W tle jest przygotowanie do rozmów: podstawy Jiry, sposoby pracy zespołu, metody testowania i to, jak mówić o brakach bez samowykluczenia się przed wysłaniem aplikacji.

Próbuję też znaleźć narzędzie, które przejmie pamiętanie za mnie. Nie tylko tabela z nazwą firmy, ale status, konkretna wersja CV, osoba kontaktowa, termin odpowiedzi, zadanie do wykonania i miejsce na notatkę po rozmowie. Pytam o gotowe trackery, lecz trafiam na linki kończące się 404. To drobna rzecz, a jednak dobrze pokazuje cały problem: zanim wyślę jedną aplikację, potrafię zbudować wokół niej projekt organizacyjny, a kiedy narzędzie nie działa, wracam do punktu wyjścia.

Tak samo z nauką. Chcę wiedzieć, co ma sens dla manualnego testera po roku pracy: podstawy automatyzacji, dobry warsztat testowy, certyfikat, konkretna książka czy ćwiczenia do rozmów. Obecna praca nie daje mi wystarczającego rozwoju, ale lista wszystkich możliwych kierunków też potrafi zamrozić. Szukam więc kolejności, nie idealnego planu na całe życie: najpierw CV i aplikacje, równolegle mały blok nauki, później następny krok.

Cała rozmowa krąży wokół uruchamiania. Jak zacząć dzień, kiedy zaplanować tydzień, co zrobić z zadaniem, które już samym istnieniem wywołuje lęk, i jak utrzymać nawyk po pierwszym zrywie. Pytam o coaching ADHD, ale pilnuję granicy: mam terapeutę i nie chcę, żeby praktyczne pytanie znów zostało zamienione w ogólną rozmowę terapeutyczną. Potrzebuję zewnętrznej struktury, przypomnienia i następnego widocznego kroku.

Nie chodzi tylko o pracę. Potrzebuję sposobu na planowanie dnia, tygodnia i miesiąca, ruszanie z zadaniami, nawyki i niegubienie wszystkiego po drodze. Mam terapeutę; tutaj nie szukam kolejnej terapii, tylko praktycznych podpórek. Następna książka to „Unwinding Anxiety”. Gdzieś między CV, trackerem i całym tym napięciem pytam jeszcze o rosyjskie podcasty z transkrypcjami, rzucam „a ty pa ruskie gawarisz” i kończę krótkim: noice.`,
    [
      gated("sensitive", `Najgorsze jest to, że nie potrafię po prostu dokończyć CV i nacisnąć „wyślij”. ADHD i duży lęk robią z prostego zadania ścianę. Potem uciekam w rozpraszacze, mam poczucie winy i jeszcze mocniej wierzę, że naprawdę ssę w zarządzaniu czasem i priorytetami. Potrzebuję rozbicia tego na małe, wykonalne ruchy, a nie kolejnego ogólnego kazania o motywacji.`, "To, na czym faktycznie utknąłem"),
    ],
  ),
  entry(
    "2023-01-24",
    "Przeprowadzka, rutyna, smoothie",
    `W przyszłym miesiącu przeprowadzka. Potrzebuję prostej listy: co spakować najpierw, co zostawić do ostatniego dnia, skąd wziąć pudła, jak opisać rzeczy i jak ogarnąć transport bez noszenia całego planu w głowie. Obok tego próbuję ułożyć zwykłą, zdrową rutynę i dostać pomoc przy najprostszych codziennych zadaniach.

Jedzenie też ma być banalne. Układam łatwe, odżywcze śniadania na tydzień i listę zakupów. Owsianka nie bardzo mi pasuje, więc szukam zamiennika. Ostatecznie zostaje smoothie z masłem orzechowym i bananem — pytam, jak je zrobić i czy to w ogóle jest sensowne odżywczo. Dzień bez wielkiej idei: pudła, transport, śniadanie i próba zrobienia odrobiny porządku, zanim zacznie się właściwa przeprowadzka.`,
  ),
  entry(
    "2023-02-20",
    "Nie wiem, co jest dalej",
    `Jest mi smutno. Pod koniec miesiąca się wyprowadzam i nie wiem, co ma być dalej. Nie jestem po prostu „nieszczęśliwy”; bardziej nie widzę teraz w życiu punktu ani niczego szczególnie ekscytującego. Przez długi czas napędzałem się wielkimi, trochę wyidealizowanymi marzeniami. Te ważne były też straszne i wymagające, więc z części z nich zrezygnowałem. Została pustka po mechanizmie, który wcześniej pchał mnie do przodu.

Praktyczny plan jest bardzo prosty i jednocześnie odległy: zarabiać więcej, odłożyć pieniądze i ruszyć w drogę może na dwa lata, a nie na krótki urlop. Szukam tanich krajów. Słowo „expat” mnie drażni — to brzmi jak sposób, żeby zachodni imigrant nie musiał nazwać siebie imigrantem.

Rozmowa zaczyna mielić te same przykłady państw. Wkurwiam się coraz bardziej, proszę, żeby ich nie powtarzać, w końcu piszę to wielkimi literami. Jest wojna w Ukrainie, świat nie jest neutralną tabelką tanich kierunków, a ja nie potrzebuję automatu, który po raz kolejny podaje mi tę samą listę.`,
    [
      gated("third_party_sensitive", `Skończył się związek trwający trzynaście lat. To nie jest mały dodatek do przeprowadzki, tylko genealogia całego „nie wiem, co dalej”. Nie próbuję jeszcze robić z tego ładnej opowieści ani puenty. Na razie jest koniec bardzo długiej relacji, wyprowadzka i brak pewności, gdzie właściwie zaczyna się moje następne życie.`, "Po trzynastu latach"),
    ],
  ),
  entry(
    "2024-07-21",
    "Dwie–trzy godziny nad Primal Fear",
    `Mam zacząć około 11:27 i przeznaczyć dwie–trzy godziny na skrypty. Najważniejsze są materiały nauczyciela i ucznia do „Primal Fear”: reported speech, uzupełnianie luk, słownictwo i zadanie do pracy w parach w breakout roomach. Potem skrypt nauczyciela do „Runaway Jury”, dostęp do pozostałych materiałów i przegląd ćwiczeń. Kiedy rozmowa zmyśla mi jakiś Contract Law, wkurwiam się — najpierw trzeba było zapytać, nad czym naprawdę pracuję.

Lista filmów rośnie szybciej niż same skrypty: „A Few Good Men”, „The Verdict”, „Michael Clayton”, „The Social Network”, „The Trial of the Chicago 7”, „Sleepers”, „The Devil’s Advocate”, „…And Justice for All”, „Spotlight”, „Marriage Story”, „A Time to Kill”, „To Kill a Mockingbird”, „My Cousin Vinny”, „Kramer vs. Kramer”. Chcę dokładnych długości i świeżych podręczników do Legal English. To jest ten rodzaj planowania, w którym konkret pomaga, ale lista w sekundę potrafi stać się osobnym projektem.

W samym „Primal Fear” nie wystarcza mi ogólne „zrób ćwiczenia”. Potrzebuję osobnej wersji teacher i student, sensownych luk, klucza, słownictwa z tłumaczeniami i materiału, który można rozdzielić między uczniów, żeby naprawdę musieli ze sobą porozmawiać. Wracam do kolejnych wersji zdań, sprawdzam reported speech i poprawiam układ. To ma być lekcja, którą da się uruchomić bez improwizowanego łatania jej już podczas zajęć. Następny jest „Runaway Jury”, ale dopiero kiedy najważniejszy skrypt przestanie wisieć jako prawie skończony.

Próbuję pilnować priorytetu, bo każda odpowiedź natychmiast otwiera następny temat. Z jednego ćwiczenia robi się lista słówek, z listy słówek tłumaczenia, z tłumaczeń pomysł na następny materiał. Dlatego wracam do pytania: co dokładnie mam zrobić w tych dwóch–trzech godzinach? Nie „rozwijać kurs”, tylko dopiąć dwa skrypty „Primal Fear”, sprawdzić, czy uczeń i nauczyciel mają komplet, i dopiero wtedy przejść dalej.

Lista filmów ma podobną pułapkę. Chcę znać rzeczywisty czas seansu, bo to decyduje, co w ogóle mogę obejrzeć i przerobić. Szukam pozycji dobrych do Legal English, ale także takich, z których da się wyjąć sceny, język i zadania. Nowe podręczniki miałyby uzupełnić filmy, nie stworzyć jeszcze jednego stosu materiałów czekających na przejrzenie.

Między poprawkami sprawdzam też rzeczy kompletnie niezwiązane z pracą. Czy dwie różne kości RAM będą współpracować, ile pamięci naprawdę potrzebuje „Wiedźmin 3”, które dramaty sądowe są najwyżej oceniane jednocześnie na IMDb i Filmwebie. Nawet pytanie o teflon wpada w środek tej samej sesji. Nie wygląda to jak skupiony blok, lecz właśnie dlatego lista priorytetów jest potrzebna: bez niej każda ciekawość natychmiast przejmuje sterowanie.

Poza pracą dzień jest poszatkowany. Układam śniadanie, lunch, zakupy i alternatywny wrap. Sprawdzam, czy RAM 32 GB będzie pasował i czy 16 GB wystarczy do „Wiedźmina 3” na wysokich. Szukam dramatów sądowych według IMDb i Filmwebu, pytam nagle, czy teflon jest bezpieczny, a tarotową transkrypcję każę przerobić na coraz bardziej absurdalny marketing.

Jest też park i książka. Dużo pracuję, ale siedzę na zewnątrz, czytam i odpoczywam. Drugi rozdział idzie łatwiej niż pierwszy. Dopytuję o scenę z prostytutką, ale bez spoilerów. Na koniec próbuję jeszcze przerobić kobietę ze zdjęcia na dziecko albo bardzo młodą osobę i irytuję się, że wynik znowu przedstawia kogoś innego. Dużo różnych rzeczy, lecz rdzeń dnia pozostaje prosty: skończyć wreszcie „Primal Fear”.`,
  ),
  entry(
    "2024-07-24",
    "Jedna kość RAM-u działa",
    `Po wymianie RAM-u komputer nie startuje. Wchodzę w BIOS, przekładam kości, sprawdzam konfiguracje. Z jedną nową kością działa, z dwiema nie. To przynajmniej jest konkret: fizyczny problem, kombinacje do przetestowania i wyraźny wynik.

Kartą dnia jest Dwójka Mieczy. W pracy lista jest dłuższa: raport wysłany, wznowione rozmowy UAT ustawione — „today is tomorrow”. Dla Delta Netherlands trzeba zdobyć dostęp do HPE ALM, potem przekazać go dalej. W Takeda Norway zostaje incident log i czekanie na defekty, testy, mobile, webchat oraz telefon. Komunikację dla Juniper Costa Rica eskaluję przez Teams i mail. Jedną rzecz po retestach można wreszcie usunąć z listy.`,
    [
      gated("third_party_sensitive", `Poza pracą myślę o tym, jak lepiej słuchać partnerki. Chcę słuchać naprawdę, a nie od razu naprawiać albo zamykać temat. Jednocześnie boję się przeciążenia: że emocji będzie za dużo, odetnę się i znowu stanę się unikający. Nie mam dziś eleganckiego rozwiązania. Jest raczej świadomość własnego mechanizmu i próba, żeby nie uruchomił się automatycznie.`, "Słuchanie bez uciekania"),
    ],
  ),
  entry(
    "2024-07-29",
    "Canto II i tysiąc rumuńskich słów",
    `Kartą dnia jest Król Mieczy. Wracam do Dantego i chcę czytać go powoli, po trzy wersy: współczesny angielski, proste wyjaśnienie, kontekst historyczny, symbolika i to, co mówią badacze. Najpierw przez pomyłkę ląduję przy Sonecie 1 Szekspira, potem wracam na właściwy tor. Oryginał włoski raz ma być, za chwilę jednak go usuwam. Canto I, Eneasz, święta Łucja, podsumowanie, obrazy — potem Canto II. Chcę rozumieć, a nie tylko odhaczać.

Obok tego próbuję zbudować naukę rumuńskiego z tysiąca najczęstszych słów. Pierwszy wynik jest tak zły, że kończy się „what the fuck? stop. delete”. Wklejam wielką listę frekwencyjną i stawiam twardy warunek: pięć historii, wyłącznie słowa z tej listy. Do tego tłumaczenie słowo po słowie, komentarz i osobne audio MP3. Sam materiał źródłowy jest ogromny, ale mój cel pozostaje mały: ograniczony język, z którego da się już zrobić coś żywego.

Przy Dantem cały czas reguluję poziom szczegółu. Nie chcę suchego streszczenia, ale nie chcę też, żeby komentarz zasłonił tekst. Pytam o las, przewodnika, Eneasza i to, dlaczego podróż w ogóle może się rozpocząć. Święta Łucja i inne postacie mają dostać kontekst, a obrazy mają pomóc zobaczyć scenę, nie tylko ozdobić odpowiedź. Kiedy układ trzech wersów działa, idę dalej; kiedy nie działa, zmieniam format. To jest czytanie jako budowa własnego wydania roboczego.

Rumuński ma odwrotny problem: nie nadmiar interpretacji, lecz nadmiar słów. Lista liczy tysiące pozycji i sama w sobie jest martwa. Historyjki mają sprawdzić, czy ze skrajnie ograniczonego materiału można dostać fabułę, powtórzenia i poczucie postępu. Dopytuję o każde słowo, tłumaczenie i konstrukcję, a potem chcę audio, żeby materiał nie został kolejną tabelą, do której nigdy nie wrócę.

W obu przypadkach walczę też z odpowiedzią, która „mniej więcej” spełnia polecenie. Jeżeli proszę o wyłącznie słowa z listy, każde słowo spoza niej psuje eksperyment. Jeżeli proszę o trzy wersy Dantego bez włoskiego, nie chcę nagle całej strony innego formatu. Stąd poprawki, zatrzymywanie i zaczynanie jeszcze raz. Nie chodzi o perfekcję dla samej perfekcji, tylko o zbudowanie materiału, któremu mogę ufać i który później da się kontynuować tym samym sposobem.

Na końcu te metody spotykają się ze zwykłym życiem. Dziesięć zajęć dla Katarzyny nie przygotuje się samo, książki na Vinted nie wystawią się od kolejnej tabeli, dentysta nadal wymaga umówienia, a CV wysłania. Lista ma pomieścić zarówno „Inferno”, jak i te przyziemne ruchy. Nie po to, żeby wszystko zrobić jednego dnia, tylko żeby żadna ważna rzecz nie zniknęła pod najbardziej interesującym aktualnie projektem.

Powstaje też zwykła lista rzeczy do ogarnięcia: wystawić książki na Vinted, popracować nad skryptem Cinematic English, umówić dentystę, przygotować dziesięć lekcji konwersacyjnych dla Katarzyny, poszukać ofert QA i wysłać CV. Czytać Dantego canto po canto. Canto I — zrobione. Potem II.

To nie jest jeden projekt, tylko kilka naraz, wszystkie próbują dostać własną metodę. Dante ma rytm trzech wersów i warstwy komentarza. Rumuński ma zamknięty słownik i historyjki. Praca oraz dom trafiają na listę. W praktyce dzień wygląda jak ustawianie reguł, które mają powstrzymać materiał przed rozlaniem się we wszystkie strony.`,
  ),
  entry(
    "2025-02-03",
    "Jedno fucking zadanie",
    `Najpierw sprawdzam drobiazg: co oznacza „Sterling A” na bransoletce. Potem cały dzień kurczy się do jednego zdania: „pls im so fucking overwhelmed i need to finish one fucking task asdoi”.

Tym jednym zadaniem jest wysłanie klientowi EE IDs. Tyle że zanim mogę je wysłać, muszę je jeszcze utworzyć. Nie potrzebuję teraz systemu życia, motywacyjnej przemowy ani rozbudowanego planu. Jest przeciążenie, literówki i jedna zależność blokująca prosty finał: najpierw stworzyć identyfikatory, potem wysłać. Jedno fucking zadanie.`,
    [gated("sensitive", `Jestem tak przeciążony, że nawet zapisanie tego wychodzi jako rwany strumień liter. Nie próbuję brzmieć spokojniej, niż jest. Chcę po prostu doprowadzić jedną rzecz do końca.`, "Przeciążenie")],
  ),
  entry(
    "2025-03-16",
    "Checklista rano, przepaść później",
    `Rano próbuję rozłożyć sprzątanie na małe ruchy: pokój, łazienka, kuchnia i korytarz. Ma być checklista przyjazna dla ADHD, może nawet trochę grywalizowana, żebym nie musiał za każdym razem wymyślać, od czego zacząć. Potem zamawianie z Biedronki Express przez Glovo: śniadanie, obiad, kolacja, coś na jutro i rzeczy, które mogą stać na półce. Pytam też najbardziej zwyczajnie, jak zrobić owsiankę.

Wieczorem dzień wraca do codzienności tak nagle, że aż absurdalnie. Szukam gier z gumową piłką i frisbee dla dwóch dorosłych i ośmiolatki. Rano checklista, później przepaść, na końcu zabawa na zewnątrz — żadna z tych warstw nie unieważnia pozostałych.`,
    [
      gated("sensitive", `Później piszę wprost: chcę się zabić. Jestem sam. Nic nie daje mi radości ani pocieszenia. Czuję się bezwartościowy i jak porażka, która zawsze nią będzie. Wczoraj też chciałem umrzeć. „I just want to die”. Potem już tylko: „Fuck it”. Nie ma tutaj sensu poprawiać tonu ani robić z tego gładkiej refleksji.`, "Przepaść"),
      gated("third_party_sensitive", `Próba zaplanowania dnia rozbija się również o napięcie w relacji. Czuję, że nie ma dla mnie miejsca w jej życiu i że jesteśmy odłączeni. To jest część tego samego załamania, ale nie cała jego przyczyna i nie materiał do rozstrzygania cudzych intencji.`, "Relacja"),
    ],
  ),
  entry(
    "2025-08-11",
    "Tirana, Konya i gdzie tu się wysrać",
    `Planowanie podróży skacze dziś po mapie. Najpierw pełny dzień i wieczór w centrum Tirany: co zobaczyć, co zjeść, co przywieźć. W środku całej turystycznej logistyki pada też bardzo praktyczne pytanie: „where to poop”. Potem Prisztina. Do tego ceny tatuaży w Albanii, Kosowie, Stambule i Polsce oraz oldschoolowe studia w Tiranie.

Druga oś to Turcja. Stambuł, Konya, Amasya, nocny pociąg, Kapadocja. Chcę wygodnych połączeń i żadnego rozciągania zwykłej trasy do sześciu dni. Maksymalnie pięć godzin w jednym odcinku brzmi rozsądnie. Sprawdzam powrót przez inne miasto, autobus Konya–Göreme i nocny Konya–Izmir albo powrót do Stambułu. Sama Konya na cały dzień wydaje się trochę nudna, więc trasa musi działać jako podróż, nie obowiązkowy katalog miejsc.

Wciąż przesuwam elementy, bo chcę zobaczyć miejsca, ale nie spędzić urlopu wyłącznie w transferach. Amasya kusi jako przystanek, nocny pociąg jako wygodny sposób na oszczędzenie dnia, Kapadocja jako oczywisty cel. Gdy propozycja robi się zbyt długa albo każe mi siedzieć wiele godzin w autobusie, odrzucam ją i wracam do prostszego układu. Konya ma sens jako część trasy, lecz nie zamierzam udawać zachwytu samym faktem, że da się tam dopisać kolejną dobę.

Tatuaże są osobnym budżetem podróży. Porównuję ceny między Albanią, Kosowem, Stambułem i Polską, ale sama najniższa kwota nie wystarczy. Szukam miejsc robiących konkretnie old school, oglądam studia w Tiranie i próbuję ocenić, czy wyjazd jest dobrym momentem na spontaniczną dziarę. To ma być pamiątka, nie losowy salon wybrany dlatego, że akurat był blisko hostelu.

Tirana też nie ma być tylko przystankiem do odhaczenia. Chcę planu od rana do wieczora, jedzenia, centrum i rzeczy, które można przywieźć. Pytam praktycznie, czasem głupio, czasem bardzo dosłownie. Prisztina pojawia się zaraz obok, więc planowanie zaczyna obejmować nie pojedyncze miasto, lecz ciąg dalszy drogi i różnice między miejscami, do których jadę.

Jedzenie jest częścią tej samej trasy, nie dodatkiem po zwiedzaniu. Szukam rzeczy lokalnych, ale możliwych do wciśnięcia w realny dzień, oraz czegoś, co da się zabrać z powrotem. Chcę wiedzieć, gdzie usiąść wieczorem w centrum i jak nie skończyć z planem, który dobrze wygląda tylko na mapie. Nawet pytanie o toaletę jest sensowniejsze niż kolejna ogólna lista atrakcji — w podróży właśnie takie szczegóły decydują, czy dzień jest przyjemny, czy męczący.

Między tym wszystkim kręci się seria głupich pytań o to, dlaczego dla Allaha seksowne miałyby być kolana albo ramiona. Próbuję wyobrazić sobie Allaha jako babcię, ale żart siada średnio: meh. Dzień ma więc jednocześnie Excela w głowie, transport, tatuaże i durne boczne korytarze rozmowy.`,
    [
      gated("sensitive", `Najważniejszy problem praktyczny nie dotyczy atrakcji, tylko leków. Sprawdzam legalność i przewóz metylofenidatu, wortioksetyny, duloksetyny i pregabaliny przez Albanię, Kosowo i Turcję. Czy wystarczy recepta, co mówią oficjalne zasady i fora, jakie mogą być konsekwencje. Bez tego cała trasa jest tylko fantazją na mapie.`, "Leki w podróży"),
    ],
  ),
  entry(
    "2025-10-21",
    "Dwie godziny piekła z GitHubem",
    `Najpierw proxy, Cloudflare Worker i połączenie cleaning-dashboardu z OpenAI. Struktura plików, komendy, klucz, poprawianie promptu, żeby odpowiedzi były bardziej żywe. Potem Git i GitHub. Złe repo, złe foldery, branch, revert, Credential Manager, SSH, PAT i 403. Po dwóch godzinach mam już tylko: „to jest jakieś popierdolone” oraz „CO TO KURWA JEST JA PIERDOLĘ”. W końcu push na master przechodzi. Następne pytanie: jak wystawić to przez GitHub Pages.

Równocześnie cleaning-dashboard zaczyna rozrastać się w Personal Dashboard. Na makiecie mają być czas, data, pogoda, jakość powietrza w Krakowie, nawyki, leki, trzeźwość, link do sprzątania, święta i wydarzenia. Potem dokładam Google Calendar, wyniki Liverpoolu i Beşiktaşu, temperaturę oraz wilgotność w pokoju, zdrowie i czytanie. Chcę przerabiać istniejące aplikacje na komponenty, a zadania do implementacji trzymać jak projekt w Trello. To już nie jest pojedyncza strona, tylko pomysł na warstwę obejmującą pół życia.

Każdy boczny pomysł od razu próbuje zostać funkcją. Skaner kodów kreskowych i dane produktów. Paragony. Bot, który wyszukuje tanie książki i porównuje je ze średnią rynkową. Wykres dwóch lat alkoholu, palenia i leków. Brudne drewno oraz półka na balkonie, popiół i odkrycie w stylu „TO JE AMELINIUM”. Kret przecięty przy goleniu, który krwawi. Pakiet w Allianz. Spray do uszu.

Przy dashboardzie nie interesuje mnie tylko dokładanie kafelków. Próbuję ustalić, jak ma się zachowywać całość: co jest widgetem, co osobną aplikacją, jak importować już istniejący moduł i jak nie zgubić kolejnych pomysłów. Rozpisuję komponenty oraz zadania, pytam o strukturę plików i o to, które informacje powinny być widoczne od razu po wejściu. Pogoda i AQI są lokalne dla Krakowa, mecze mają dotyczyć konkretnych drużyn, dane z pokoju mają być realnym pomiarem. Zwykła lista funkcji zaczyna przypominać specyfikację osobistego systemu operacyjnego.

Równie ważne są rzeczy małe i brudne, bo to właśnie one znikają w ładnych opisach projektu. Balkon nie jest abstrakcyjnym modułem „home”; jest półką, starym drewnem, popiołem i materiałem, którego nie potrafię od razu rozpoznać. Zdrowie to nie tylko wykres, lecz krwawiący pieprzyk po goleniu, spray do ucha i pytanie, czy hałas potrafi rozwalać codzienne funkcjonowanie. Książki to nie ogólna „kultura”, tylko pomysł na bota, który ma znaleźć egzemplarz naprawdę tańszy od rynku.

Techniczne piekło z GitHubem jest przy tym pierwszym testem, czy ten projekt w ogóle potrafię wynieść poza własny folder. Myli mi się nazwa gałęzi, repozytorium nie wygląda tak, jak powinno, uwierzytelnianie przerzuca mnie między metodami. Cofam, ponawiam, czyszczę poświadczenia, próbuję SSH i tokenu. Dopiero kiedy master faktycznie ląduje zdalnie, mogę myśleć o Pages. Sukces jest mały i spóźniony o dwie godziny, ale jest konkretny: dashboard po raz pierwszy ma zdalną historię, a nie tylko lokalne pliki.

Pytam o hałas i autyzm w codziennym życiu, po czym wkurwiam się, kiedy odpowiedź idzie w stronę testów zamiast tego, jak się z tym normalnie funkcjonuje. Wklejam hasło o noumenie z Wikipedii, proszę o wersję brainrot, a potem o włoski brainrot. Na koniec jeszcze śmieszny niemiecki. Dzień jest dokładnie taki jak powstający dashboard: wszystko naraz, od zdrowia i własnej historii po metalową półkę, ale każda rzecz chce mieć swoje miejsce i własny interfejs.`,
    [
      gated("sensitive", `Wśród widgetów chcę też zobaczyć dane o lekach, alkoholu, papierosach i trzeźwości. To nie ma być dekoracyjny wykres produktywności. Ma pokazać dwa lata realnego życia i zależności, których nie widać, kiedy wspomnienia zostają osobno.`, "Historia w danych"),
    ],
  ),
  entry(
    "2026-05-09",
    "Cmentarz, Tatra i jebane Gemini",
    `Po północy liczę jedzenie i picie: whisky sour, półtorej Tatry, cztery kostki czekolady — nie cztery tabliczki — pięć dużych kawałków hawajskiej i wafle ryżowe. Podaję 184 cm, 31 lat i 94 kg, chcę tabelę. Kiedy widzę wynik, panikuję, że już zawsze będę gruby. Prawie natychmiast z tego lęku robi się pomysł techniczny: podłączyć dashboard do Open Food Facts, żeby takich rzeczy nie liczyć za każdym razem od zera.

Potem rower po zimie. Rdza, hamulce, narzędzia i czyszczenie. Analiza wydatków z banku. Rejestracja jako kurier Glovo albo Wolt w Krakowie i pytanie, które aplikacje zwiększą szanse na zlecenia. Każda codzienna rzecz w sekundę zamienia się w procedurę albo moduł.

Jestem też przez kilka godzin we Wrocławiu. Chcę zobaczyć stary cmentarz żydowski i rzeczy goth/creepy. Czytam nagrobki, próbuję zrozumieć „Gatte/Ruhe”, a hebrajskie litery przez moment wyglądają jak „piłka nożna”. Szukam muzyki pasującej do cmentarza i wkurwiam się, kiedy rozmowa zmyśla informacje o Tribulation. Po drodze kontekst do książki o świętym Franciszku, pół obwarzanka, połowy dań z menu, Pilsner i kolejne kalorie. Jeszcze pinsa z Biedronki.

Wrocław ma być krótki, więc zamiast ogólnego przewodnika potrzebuję trasy na kilka godzin. Stary Cmentarz Żydowski pasuje idealnie: kamień, inskrypcje, zarośnięte alejki i możliwość czytania miasta przez ślady ludzi, a nie przez listę „top 10”. Dopytuję o gotyckie i trochę niepokojące miejsca w pobliżu. Na samym cmentarzu próbuję rozszyfrowywać słowa z nagrobków i raz po raz wrzucam kolejne pytanie, bo każde nazwisko albo znak otwiera następny boczny temat.

Jedzenie znowu liczę po kawałkach. Nie cały obwarzanek, tylko pół. Nie całe dania, tylko ich części. Pilsner, pozycje z menu, później pinsa. To trochę śmieszne po nocnej katastroficznej tabeli, ale dokładnie tak wygląda próba odzyskania kontroli: korygować dane, kiedy są błędne, zamiast uznać, że skoro noc była chaotyczna, to reszta dnia też nie ma znaczenia.

Rower i telefon spinają dwa końce tej samej codzienności. Rower stał przez zimę, więc pytam, czego potrzebuję do rdzy, hamulców i czyszczenia, zanim po prostu na niego wsiądę. Telefon powinien być narzędziem do biletów, mapy i powrotu, ale muli, a długie przytrzymanie przycisku uruchamia Gemini zamiast menu zasilania. Nie chcę kolejnej warstwy „pomocy”; chcę, żeby podstawowe urządzenie znowu robiło przewidywalnie to, co mu każę.

Na końcu logistyka powrotu: który bilet tramwajowy, skąd jedzie pociąg do Krakowa o 20:57 i na który peron mam trafić. Telefon działa wolno, a Gemini przejęło przycisk zasilania. Chcę tylko przyspieszyć urządzenie i odzyskać normalne sterowanie, więc kolejne okrężne instrukcje kończą się czystym: jebane Gemini.`,
    [
      gated("sensitive", `Najbardziej nerwowa część dnia to nie sam bilans kalorii, tylko skok od „co zjadłem” do „będę już zawsze gruby”. Wiem, że poprawiam nawet liczbę kostek czekolady, a mimo to kalkulacja uruchamia znacznie większy lęk niż wynikałoby z jednej nocy.`, "Po nocnym liczeniu"),
    ],
  ),
  entry(
    "2026-07-07",
    "Papier czy L4",
    `Rozpisuję lipiec i sierpień, bo inaczej wszystko zlewa się w jedną ścianę. Włochy 13–19 lipca, My Chemical Romance piętnastego, urlop, potem praca 27–31 lipca. Brutal Assault 3–7 sierpnia, powrót dziesiątego. Na papierze wygląda to jak lato pełne konkretnych punktów. Pomiędzy nimi jest jednak praca, do której samo logowanie sprawia, że nie chcę żyć.

Chcę odejść i znaleźć coś za przynajmniej 1500 zł więcej na rękę. Teraz mam 7464 brutto i trzy miesiące wypowiedzenia. Od trzech lat nie potrafię naprawdę zacząć szukać nowej pracy, bo bieżąca zabiera całą energię. Stres trwa całą dobę, a wolny czas chciałbym przeznaczyć na życie, wyjazdy i odpoczynek, nie na kolejną zmianę po zmianie.

Psychiatra i psycholog mówią, żeby nie rzucać impulsywnie. Układam więc kompromis: po powrocie 10 sierpnia wziąć L4 związane ze zdrowiem psychicznym, ogarnąć życie, budżet i mieszkanie, uruchomić szukanie pracy, a wypowiedzenie złożyć dopiero, kiedy będzie oferta. To nadal ryzykowne i nadal nie wiem, ile siły naprawdę odzyskam, ale przynajmniej nie jest to wybór między natychmiastowym skokiem a tkwieniem bez końca.

Chcę wykorzystać zwolnienie nie jako pustą przerwę, tylko jako bufor. Najpierw policzyć, ile naprawdę kosztuje życie i ile czasu dają oszczędności. Posprzątać mieszkanie oraz sprawy, które rosną od miesięcy. Dopiero z trochę stabilniejszego miejsca poprawić CV, zobaczyć, jakie oferty istnieją, i regularnie aplikować. Najbezpieczniejsza wersja zakłada znalezienie pracy przed wypowiedzeniem. Najbardziej kusząca mówi, żeby rzucić wszystko natychmiast. Próbuję zbudować coś pomiędzy, bo żadna z tych skrajności nie wygląda dziś jak decyzja podjęta z wolnej głowy.

Wyjazdy są jednocześnie odpoczynkiem i terminami granicznymi. Przed Włochami nie naprawię całego życia. Po koncercie wracam jeszcze do pracy. Brutal Assault daje następny konkretny punkt, a 10 sierpnia staje się datą, od której miałby się zacząć właściwy plan ratunkowy. Wiem, że kalendarz sam niczego nie załatwi, ale bez niego każdy dzień wygląda jak wieczne „później”.

W tej układance jest jeszcze pensja i bardzo przyziemny próg zmiany. Nie chcę odejść do czegokolwiek, co tylko inaczej nazwie ten sam problem; celuję przynajmniej w 1500 zł więcej na rękę. Jednocześnie nie mam teraz przestrzeni, żeby po pracy prowadzić pełny drugi etat pod tytułem „szukanie pracy”. To właśnie uzasadnia L4 jako czas odzyskania zdolności do działania, a nie magiczną gwarancję, że w kilka tygodni znajdę idealną ofertę i naprawię wszystko.

Obok całej tej ciężkiej kalkulacji pojawia się absurdalny obrazek: wiewiórka wielkości człowieka, siedząca na fotelu i jedząca orzecha. Tak, dokładnie to ma powstać.`,
    [
      gated("sensitive", `Wypalenie nie jest metaforą. Praca odpala depresję i myśli samobójcze, a perspektywy w obecnym miejscu nie widzę żadnej. Chcę wrócić do życia, ale boję się, że zanim przygotuję bezpieczne wyjście, znowu całą energię zużyję na samo przetrwanie kolejnego dnia pracy.`, "Skrajne wypalenie"),
    ],
  ),
  entry(
    "2026-08-17",
    "Hyperfocus na przepisywanie",
    `Od rana hyperfocus na przepisywanie dziennika. Wrzucam kolejne wpisy z 2015 i 2016, wiersze, fragmenty dawnego życia. Chcę zobaczyć ewolucję młodego mnie, własną filozofię, korelacje między poezją i dziennikami, autorów oraz książki, które naprawdę wtedy pracowały w głowie. Pytam o Spinozę, Kołakowskiego i Deweya. Obok tego próbuję ruszyć drzewo genealogiczne z bardzo skąpych danych rodzinnych i sprawdzam, dlaczego Geneteka niczego nie pokazuje.

Duża część dnia schodzi też na ilustracjach do starych wpisów. Renesans, potem znowu scena przy biurku, choć miało ich nie być. Przypominam, że nie mam kręconych włosów. Każę wrócić do pełnego renesansu, potem proszę o coś kompletnie abstrakcyjnego i eksperymentalnego, a następnie wkurwiam się, że wynik nadal nie potrafi wyjść z poprzedniego kontekstu. Pojawia się nawet flaga Ukrainy, nie wiadomo po co. „Wygląda to jak gówno. Gratuluję xD”.

W innych oknach układam listy filozoficzne, mapuję stare archiwum TORG, pytam o narzędzia genealogiczne, projektuję czarno-złoty herb piłkarski i okładki wydarzeń dla premier płyt. Cult of Luna, Chelsea Wolfe, Afghan Whigs, Behemoth, Chat Pile, Emma Ruth Rundle, Eivør, Mastodon, Uncle Acid, Godflesh, The Ocean. Sprawdzam premiery 2026/27 i historię ogłoszeń Brutal Assault 2027. Materiał jest ogromny, ale faktyczny dzień odbywa się przy jego porządkowaniu.

Stare dzienniki nie są tylko tekstem do przepisania. Oglądam, jak zmieniały się zainteresowania, język, nastrój i sposób myślenia o działaniu. Chcę mapy życia: daty, aktywności, książki, muzyka, wyjazdy, pomysły, załamania i powroty do systematyczności. Wklejam kolejne fragmenty, a potem pytam, co naprawdę z nich wynika, zamiast przyjmować pierwszą efektowną interpretację. TORG ma dostarczyć inną warstwę tego samego okresu — mniej uporządkowaną, pisaną publicznie i często zupełnie innym tonem.

Genealogia zaczyna się znacznie skromniej. Mam przybliżone albo dokładne daty urodzenia babć, kilka nazwisk i miejsc, ale wyszukiwarki nie zwracają oczekiwanych rekordów. Pytam, gdzie szukać i jak zapisywać niepewność, żeby nie zamienić braku danych w zmyśloną gałąź drzewa. To znowu ta sama potrzeba co przy dziennikach: połączyć rozproszone ślady, ale nie udawać, że wiadomo więcej, niż naprawdę wiadomo.

Wieczorem zjazd. Wczoraj jednak poszedłem się z nimi spotkać po południu. Dzisiaj, kiedy wychodzę do Żabki, zaczyna padać; w drodze powrotnej jest już zajebista ulewa. Kilkadziesiąt sekund na dworze i po wejściu do domu nagły powrót wspomnienia letniej burzy z Jess. Jest pusto i samotnie.`,
    [
      gated("sensitive", `Rano wziąłem tylko 150 mg pregabaliny, choć wczoraj łącznie było 600 mg. Dokładam kolejne 150 mg, ale wypijam też dwa piwa. Nie chcę pić, a jednocześnie mam ochotę je szybko wydoić. Dochodzą dwie paczki chipsów i wkurw na wagę: jestem blisko najwyższej, od 1 maja praktycznie zero progresu.`, "Zjazd"),
      gated("third_party_sensitive", `Wkurwiam się na Weronikę, bo upomina się o odpowiedź na coś z Instagrama, a mnie takie naciskanie odpala jeszcze bardziej. Jeszcze bardziej wkurza mnie psychiatrka. Minęła połowa L4, nadal nie ustawiła wizyty i mam spędzić dwa tygodnie w niepewności, czy dostanę kolejne zwolnienie. Muszę napisać przez ZnanyLekarz. „To jest kurwa żenada. Ja pierdolę.”`, "Połowa L4"),
    ],
  ),
  entry(
    "2026-09-17",
    "Kilka systemów naraz",
    `Dzień jest właściwie wielką sesją projektowania dashboardu. Finance przechodzi od audytu i fundamentów przez klasyfikacje, rachunki oraz onboarding aż do paragonów i produktów. Nie chcę jedenastu osobnych promptów i czekania po każdym kroku; chcę większych, kontrolowanych pakietów z raportami i testami. Oddzielny widget rachunków ma zostać poręczną przypominajką na wierzchu, ale dane powinny być zintegrowane z budżetem.

Najważniejsza obserwacja: po transakcji z Biedronki albo Żabki nie da się zgadnąć, czy kupiłem jedzenie, chemię czy słodycze. Sama transakcja może dostać tylko ogólną kategorię „zakupy”. Dopiero paragon, OCR i słownik produktów pozwolą zejść niżej. Manualne uzupełnianie też nie może wyglądać jak księgowość dla księgowego. Chcę finansowego Akinatora, który pokazuje płatność i zadaje proste pytania: sklep fizyczny, przelew, bilet, coś innego? Powstaje nawet osobny dżinn-doradca z przezroczystym tłem do okienka HTML.

Androidowa aplikacja do paragonów najpierw wygląda „strasznie chujowo”, potem wysyła dokumenty, ale nic na nich nie widać. Konfiguruję ADB po angielsku, próbuję połączenia bezprzewodowego, dostaję jakieś „unsuccessful”, w końcu aplikacja się otwiera. Wklejam później raport z naprawy, ale mój własny werdykt pozostaje prosty: OCR jest „chujowy jak barszcz”, data koniecznie ma być DD/MM/YYYY, nie amerykański zapis. To jest jakiś start, ale wymaga uinteligentnienia.

Równolegle wklejam serię raportów Codexa, które opisują kolejne fazy Language Dashboardu jako zakończone: gamifikację, słownik, phrasebook i curriculum. Traktuję je tutaj jako raporty do dalszej decyzji, nie własne ustalenie faktów o kodzie. Na ich podstawie pytam o następny kierunek: darmowe API do jakościowego generowania norweskich tekstów, bo nie chcę wpaść w opłaty. Wybieram Gemini pod warunkiem, że nie będzie produkowało bullshitu, a do wygenerowanych tekstów chcę norweskie audio z istniejącego Google Cloud TTS. Pojawia się jeszcze pomysł historii Erika: tekst startujący z pulą stu słów, rosnący razem z rozumieniem słownictwa i konstrukcji, z grammar miningiem oraz kontrolą narastającego kontekstu.

Job Hunt nie może być jednym workiem. QA w Krakowie, prace dorywcze w Krakowie i praca fizyczna w Norwegii to różne ścieżki, których nie ma sensu porównywać jedną liczbą. Jestem na L4 do 4 października, nadal mam pracę i trzy miesiące wypowiedzenia. Najpierw chcę normalnie pogadać o powrocie do życia i dorabianiu, dopiero potem projektować widget. Ostatecznie zaczyna powstawać architektura ze ścieżkami, źródłami, parserem AI, ochroną przed banami i testami kariery na początku.

Do tego Kermit: lokalny chatbot w prawym dolnym rogu, którego można obudzić i uśpić. Ma znać szczegółową dokumentację całego systemu, integracje, dane i statystyki, mieć charakter, ale krytycznie pozostać read-only. Rozważam hostowanie na laptopie albo przyszłym serwerze. Powstaje też pytanie o naprawdę AI-native system operacyjny, osobista generowana gazeta — najpierw mailem, kiedyś drukowana — oraz izolację wielkiego serwera treningowego od reszty aplikacji.

Wieczorem wracam do rzeczy, od której wyrośnie samo History Wiki: historia rozmów ChatGPT jest długa, a panel historii prawie bezużyteczny. Chcę ją skatalogować, przeszukiwać, grupować i regularnie eksportować. Dziś jeszcze pytam o rosyjskiego drona przy granicy, numer telefonu, mBankowe zestawienia, nową playlistę z małą ilością basu, wyszukiwanie na Instagramie i przypominam sobie stary pomysł grywalizacji treningu jako podróży z Krakowa. Kilka systemów naraz — ale właśnie dlatego potrzebuję archiwum, które pokaże nie tylko ich nazwy, lecz konkretne rozmowy, z których każdy wyrósł.`,
    [
      gated("sensitive", `Pod spodem całego projektowania jest powód, dla którego w ogóle buduję Finance i Job Hunt: chcę wrócić do życia i pracy bez ponownego wpadnięcia w ten sam układ. L4 daje trochę miejsca, ale jego koniec jest blisko. Mam oszczędności, nadal zatrudnienie i okres wypowiedzenia, więc nie jestem bez żadnego zabezpieczenia — jestem za to zmęczony, niepewny i próbuję zamienić to w realne ścieżki zamiast jedną desperacką decyzję.`, "Po co to wszystko buduję"),
    ],
  ),
];
