document.addEventListener("DOMContentLoaded", function() {
    const chartsData = JSON.parse('{{ charts_data | tojson | safe }}');

    for (const [name, data] of Object.entries(chartsData)) {
        const trace = {
            x: data.date,
            y: data.value,
            type: 'scatter',
            mode: 'lines+markers',
            name: name
        };
        Plotly.newPlot(name.replace(' ', '_'), [trace], {
            title: name
        });
    }
});
