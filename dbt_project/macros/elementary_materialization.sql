{#-
    Required by Elementary on dbt-core 1.8+: without this override, the
    "test" materialization dbt-core ships changed in a way that leaves
    Elementary's result tables empty even though `dbt test` itself reports
    no errors. See https://docs.elementary-data.com (Elementary's
    dbt-core 1.8+ compatibility notes) for background.
-#}
{% materialization test, default %}
{{ return(elementary.materialization_test_default()) }}
{% endmaterialization %}
