import { expect } from 'vitest'

import { sandboxTest } from './setup'

sandboxTest('display data', async ({ sandbox }) => {

  // plot random graph
  const result = await sandbox.notebook.execCell(`
        import matplotlib.pyplot as plt
        import numpy as np

        x = np.linspace(0, 20, 100)
        y = np.sin(x)

        plt.plot(x, y)
        plt.show()
        `)

  const image = result.results[0]
  expect(image.png).toBeDefined()
  expect(image.text).toBeDefined()
})
