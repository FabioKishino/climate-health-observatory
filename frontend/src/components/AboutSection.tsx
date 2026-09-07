const REPO_URL = "https://github.com/FabioKishino/climate-health-observatory";

export default function AboutSection() {
  return (
    <section className="w-full max-w-4xl mt-12 pt-8 border-t border-black/10 dark:border-white/15 text-sm leading-relaxed text-black/70 dark:text-white/70">
      <h2 className="text-base font-semibold text-foreground mb-3">About this project</h2>
      <p className="mb-3">
        This dashboard correlates daily climate data from INMET (Brazil&rsquo;s National
        Institute of Meteorology) with respiratory-cause hospital admissions from
        DataSUS/SIH-RD (Brazil&rsquo;s public health system), for the municipality of
        Curitiba, Paraná, over the last 24 months — asking whether climate variation
        correlates with spikes in respiratory hospital admissions.
      </p>
      <p className="mb-3">
        Climate readings are aggregated to daily station-level metrics; admissions are
        matched to a municipality&rsquo;s nearest weather station (not every municipality has
        its own station). Both charts above sum/average across whatever data is available
        for each period — DataSUS admissions typically lag by about two months, so the most
        recent weeks or months may show climate data without matching admissions data yet.
      </p>
      <p>
        Source code, the full data pipeline (ingestion, dbt models, tests, CI/CD, and
        observability), and the architecture decision records explaining the trade-offs
        behind this project are on{" "}
        <a
          href={REPO_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="underline underline-offset-2 hover:text-foreground"
        >
          GitHub
        </a>{" "}
        — see{" "}
        <a
          href={`${REPO_URL}/tree/main/docs/adr`}
          target="_blank"
          rel="noopener noreferrer"
          className="underline underline-offset-2 hover:text-foreground"
        >
          docs/adr
        </a>{" "}
        for the architecture decision records.
      </p>
    </section>
  );
}
