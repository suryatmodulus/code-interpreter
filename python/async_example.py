import asyncio

from dotenv import load_dotenv

from e2b_code_interpreter import AsyncCodeInterpreter

load_dotenv()

code = """
import matplotlib.pyplot as plt
import numpy as np

# Data for plotting
x = np.linspace(0, 10, 100)
y1 = np.sin(x)
y2 = np.cos(x)
y3 = x**2
y4 = np.sqrt(x)

# Create a figure with multiple subplots
fig, axs = plt.subplots(2, 2, figsize=(10, 8))

# Plotting on the different axes
axs[0, 0].plot(x, y1, 'r')
axs[0, 0].set_title('Sine Wave')
axs[0, 0].grid(True)

axs[0, 1].plot(x, y2, 'b')
axs[0, 1].set_title('Cosine Wave')
axs[0, 1].grid(True)

axs[1, 0].plot(x, y3, 'g')
axs[1, 0].set_title('Quadratic Function')
axs[1, 0].grid(True)

axs[1, 1].plot(x, y4, 'm')
axs[1, 1].set_title('Square Root Function')
axs[1, 1].grid(True)

# Adjust layout to prevent overlap
plt.tight_layout()

# Display the figure
plt.show()
"""


async def create_sbx(sbx, i: int):
    await asyncio.sleep(i * 0.01)
    return (
        await sbx.notebook.exec_cell(f"os.getenv('TEST')", envs={"TEST": str(i)})
    ).text


async def run():
    sbx = await AsyncCodeInterpreter.create(
        debug=True,
    )
    result = await sbx.notebook.exec_cell(code)

    print("".join(result.logs.stdout))
    print("".join(result.logs.stderr))
    if result.error:
        print(result.error.traceback)

    print(result.results[0].formats())
    print(result.results[0].elements.elements)
    # print(result.results[0].data['graphs'][0]['data'])
    # print(result.results[0].data['graphs'][0]['data'][0])
    # print(result.results[0].data['graphs'][0]['data'][1])
    # print(result.results[0].data['graphs'][0]['data'][2])

    await sbx.kill()


asyncio.run(run())
