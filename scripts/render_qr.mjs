import QRCode from 'qrcode'

const target = process.argv[2]

if (!target) {
  console.error('QR target is required.')
  process.exit(1)
}

try {
  const svg = await QRCode.toString(target, {
    type: 'svg',
    margin: 1,
    width: 260,
    color: {
      dark: '#04111f',
      light: '#ffffff',
    },
  })
  process.stdout.write(svg)
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error))
  process.exit(1)
}
