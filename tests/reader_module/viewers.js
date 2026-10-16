export function register({ React }) {
  function RunReading({ run, results }) {
    const [value, setValue] = React.useState()
    React.useEffect(() => {
      let current = true
      const output = run.outputs.find(output => output.port_type.contract_id === 'reader_demo.temperature')
      results.value({ node_id: output.node_id, output_port: output.output_port, value_index: 0 })
        .then(reading => { if (current && reading) setValue(reading.value.temperature) })
      return () => { current = false }
    }, [run, results])
    return React.createElement('p', null, value === undefined ? 'Reading saved run…' : `Saved run temperature: ${value} °C`)
  }
  return {
    RunReading,
    Celsius: ({ reading }) => React.createElement('p', null, `${reading.value.temperature} °C`),
    Fahrenheit: ({ reading }) => React.createElement('p', null, `${reading.value.temperature * 9 / 5 + 32} °F`),
  }
}
