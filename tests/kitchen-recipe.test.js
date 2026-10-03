import { describe, expect, it } from "vitest";
import { renderRecipeText } from "../js/kitchen-recipe.js";

describe("kitchen recipe formatter", () => {
  it("renders section headings, ingredient tables and numbered steps", () => {
    const html = renderRecipeText(`**Składniki**

| Produkt | Ilość |
| --- | --- |
| Kurczak | 400 g |

**Przygotowanie**

1. **Przyprawy:** Natrzyj mięso.
2. Piecz przez **16 minut**.`);

    expect(html).toContain("<h2>Składniki</h2>");
    expect(html).toContain("<th>Produkt</th>");
    expect(html).toContain("<td>400 g</td>");
    expect(html).toContain("<h2>Przygotowanie</h2>");
    expect(html).toContain("<ol>");
    expect(html).toContain("<strong>Przyprawy:</strong>");
  });

  it("accepts plain section names and safely escapes pasted HTML", () => {
    const html = renderRecipeText(`Składniki

<img src=x onerror=alert(1)>

Przygotowanie

- Gotowe`);

    expect(html).toContain("<h2>Składniki</h2>");
    expect(html).toContain("&lt;img src=x onerror=alert(1)&gt;");
    expect(html).not.toContain("<img");
    expect(html).toContain("<ul><li>Gotowe</li></ul>");
  });
});
