{% macro get_brazil_region(state_column) %}
{#-
    Maps a Brazilian state (UF) abbreviation to its official IBGE
    macro-region. Written as a case expression (rather than pulled from a
    seed) so that dim_location automatically derives the correct region
    for any future state without needing a lookup-table update — the
    project is scoped to Parana today, but this is meant to keep working
    unchanged if the geographic scope expands (see docs/adr/0004).
-#}
    case {{ state_column }}
        when 'AC' then 'Norte'
        when 'AP' then 'Norte'
        when 'AM' then 'Norte'
        when 'PA' then 'Norte'
        when 'RO' then 'Norte'
        when 'RR' then 'Norte'
        when 'TO' then 'Norte'
        when 'AL' then 'Nordeste'
        when 'BA' then 'Nordeste'
        when 'CE' then 'Nordeste'
        when 'MA' then 'Nordeste'
        when 'PB' then 'Nordeste'
        when 'PE' then 'Nordeste'
        when 'PI' then 'Nordeste'
        when 'RN' then 'Nordeste'
        when 'SE' then 'Nordeste'
        when 'DF' then 'Centro-Oeste'
        when 'GO' then 'Centro-Oeste'
        when 'MT' then 'Centro-Oeste'
        when 'MS' then 'Centro-Oeste'
        when 'ES' then 'Sudeste'
        when 'MG' then 'Sudeste'
        when 'RJ' then 'Sudeste'
        when 'SP' then 'Sudeste'
        when 'PR' then 'Sul'
        when 'RS' then 'Sul'
        when 'SC' then 'Sul'
        else 'Unknown'
    end
{% endmacro %}
