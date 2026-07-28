# Briefing — Arte final para t-shirt (PDF vetorial)

*Documento para enviar ao designer externo. A justificação técnica de cada ponto
está em [reusable-pipeline.md](reusable-pipeline.md) §2, em inglês.*

---

Olá,

Para além da arte final para produção, o ficheiro que nos enviares vai também
alimentar um **modelo 3D da t-shirt** que usamos na comunicação do evento. Esse
processo lê o teu ficheiro e **mede-o** — cores, ângulos, espessuras e posições
são extraídos diretamente do PDF, não copiados à mão.

Por isso há alguns requisitos que saem do habitual. Nada aqui é difícil de
cumprir, mas **quase todos falham em silêncio**: o ficheiro abre bem no
Illustrator, parece perfeito no ecrã, e só damos pelo problema no fim. Daí o
detalhe.

---

## O que precisamos

**Um PDF vetorial, uma página**, com os desenhos técnicos planos da frente e das
costas lado a lado, mais a arte das mangas (ou outras peças) à parte e
identificada.

---

## Requisitos obrigatórios

**1. Vetorial a sério.** Traçados vetoriais, não uma imagem exportada dentro de
um PDF. Não achatar («flatten») nem rasterizar na exportação.

**2. Todo o texto convertido em curvas.** *Type → Create Outlines.* Texto vivo é
**invisível** para o nosso processo — não dá erro, simplesmente desaparece do
resultado. É o erro mais provável de todos.

**3. Cores sólidas, sem gradientes, transparências ou modos de fusão.** Cada
forma com uma cor chapada. Gradientes e transparências saem com a cor errada.
(A serigrafia também não os reproduz, por isso normalmente já não existem.)

**4. Sem máscaras de recorte.** Expandir ou eliminar todas as *clipping masks*
antes de entregar. O que estiver escondido por uma máscara **volta a aparecer**
no nosso processo — o resultado parece um ficheiro corrompido, com formas soltas
espalhadas pela página.

**5. Contornos expandidos.** *Object → Path → Outline Stroke.* Linhas tracejadas
sem expandir saem contínuas.

**6. Desenho técnico plano, à escala real, em milímetros.** A peça vista de
frente, esticada e pousada — **não** uma simulação vestida, nem uma foto, nem uma
vista em três quartos.

> Este é o ponto mais importante e o mais fácil de interpretar mal, porque o
> instinto é entregar algo parecido com a t-shirt acabada. Precisamos do
> contrário: o desenho plano, com as proporções do molde. É isso que nos permite
> assentar a arte no modelo 3D com precisão — a partir de uma simulação vestida
> não é possível.

**7. Sangria em todos os bordos.** Onde a arte chega a uma costura (ombro, cava,
lateral, bainha), deve **passar para lá dela** — 2 cm chegam. Não recortar a arte
pelo contorno da peça. O recorte é feito por nós, com a geometria exata do
modelo; arte já aparada só pode ficar pior.

**8. Logótipos de terceiros.** Vetoriais sempre que possível. Se só existirem em
imagem, servem — mas a **300 dpi ou mais no tamanho final** de aplicação, em
escala de cinzentos, RGB ou CMYK.

---

## Ajuda muito (não é bloqueante)

- **Indicar o tamanho a que o desenho está feito** (S, M, L…) e **uma medida real
  de referência** — o meio-peito da peça esticada é a mais prática. Sem isto, a
  escala tem de ser deduzida.
- **Agrupar e nomear os elementos** — riscas, logótipo, marcas de patrocinadores.
  Poupa-nos identificar cada forma uma a uma.
- **Indicar a paleta por valores** (HEX ou CMYK) na nota de entrega, mesmo que já
  esteja no ficheiro.
- **Guardar o ficheiro editável** (`.ai` ou `.svg`). Não precisamos dele para o
  processo, mas é de lá que sai qualquer correção.

---

## Checklist antes de enviar

- [ ] PDF vetorial, uma página, não achatado
- [ ] Texto todo em curvas
- [ ] Sem gradientes, transparências ou modos de fusão
- [ ] Sem máscaras de recorte
- [ ] Contornos expandidos
- [ ] Desenho técnico plano, escala real em mm
- [ ] Sangria de ~2 cm em todos os bordos
- [ ] Logótipos vetoriais, ou ≥300 dpi no tamanho final
- [ ] Tamanho de referência e uma medida real indicados
- [ ] Paleta indicada em HEX ou CMYK
- [ ] Ficheiro editável guardado

---

## O que não serve

Para evitar uma ida e volta — nenhum destes funciona, por muito bem que fique no
ecrã:

- PDF, PNG ou JPG exportado a partir de uma **simulação 3D** ou de uma maqueta
  vestida
- PSD com a arte já deformada sobre a foto de uma t-shirt
- PDF achatado ou rasterizado na exportação
- Arte recortada pelo contorno da peça, sem sangria

Qualquer dúvida, é só dizer — mais vale esclarecer antes do que refazer depois.

Obrigado!
