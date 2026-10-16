export function register({ React }) {
  return {
    Celsius: ({ reading }) => React.createElement('p', null, `${reading.value.temperature} °C`),
    Fahrenheit: ({ reading }) => React.createElement('p', null, `${reading.value.temperature * 9 / 5 + 32} °F`),
  }
}
