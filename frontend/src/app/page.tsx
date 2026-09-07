import AboutSection from "@/components/AboutSection";
import ClimateHealthDashboard from "@/components/ClimateHealthDashboard";

export default function Home() {
  return (
    <main className="flex-1 flex flex-col items-center px-6 py-10 sm:py-16">
      <header className="w-full max-w-4xl mb-8">
        <h1 className="text-2xl font-semibold text-foreground">
          Climate x Public Health Observatory
        </h1>
        <p className="mt-1 text-sm text-black/60 dark:text-white/60">
          Curitiba, Paraná, Brazil — average temperature vs. respiratory hospital admissions
        </p>
      </header>

      <ClimateHealthDashboard />
      <AboutSection />
    </main>
  );
}
