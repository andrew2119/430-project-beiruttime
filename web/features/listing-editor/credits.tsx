import manifest from "../../../demo/images-manifest.json";
import Image from "next/image";
import { BidiReference } from "@beirut-time/ui";
import { copy } from "./copy";
export default function Credits({ locale }: { locale: "en" | "ar" }) {
  const t = copy(locale);
  return (
    <div className="le-page">
      <header className="le-page-header">
        <div>
          <p className="le-eyebrow">WIKIMEDIA COMMONS</p>
          <h1>{t.credits}</h1>
          <p>{t.creditsIntro}</p>
        </div>
      </header>
      <div className="le-credits-grid">
        {manifest.assets.map((asset) => (
          <article className="le-credit" key={asset.id}>
            <div className="le-credit-image">
              <Image
                src={"/demo/watches/" + asset.file}
                alt={locale === "ar" ? asset.alt_ar : asset.alt_en}
                width={asset.local_dimensions[0]}
                height={asset.local_dimensions[1]}
                unoptimized
                sizes="(max-width:850px) 90vw, 400px"
              />
              <span>{t.demo}</span>
            </div>
            <div className="le-credit-copy">
              <h2>
                <BidiReference>{asset.title}</BidiReference>
              </h2>
              <p>
                <BidiReference>{asset.author}</BidiReference> ·{" "}
                <BidiReference>{asset.license}</BidiReference>
              </p>
              <p>{t.changes}</p>
              <div className="le-inline">
                <a href={asset.source_url} target="_blank" rel="noreferrer">
                  {t.source} ↗
                </a>
                <a href={asset.license_url} target="_blank" rel="noreferrer">
                  {t.license} ↗
                </a>
              </div>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}
