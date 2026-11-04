import manifest from "../../../demo/images-manifest.json";
import Image from "next/image";
import { BidiReference } from "@beirut-time/ui";
import { copy } from "./copy";
import { PageHeader, PageLayout } from "@/shell/page-header";
export default function Credits({ locale }: { locale: "en" | "ar" }) {
  const t = copy(locale);
  return (
    <PageLayout className="le-page">
      <PageHeader title={t.credits} count={t.creditsIntro} lead={<span className="le-eyebrow">WIKIMEDIA COMMONS</span>} />
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
    </PageLayout>
  );
}
