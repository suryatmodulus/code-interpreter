from e2b_code_interpreter.code_interpreter_sync import CodeInterpreter


def test_display_data(sandbox: CodeInterpreter):
    # plot random graph
    result = sandbox.notebook.exec_cell(
        """
        import matplotlib.pyplot as plt
        import numpy as np

        x = np.linspace(0, 20, 100)
        y = np.sin(x)

        plt.plot(x, y)
        plt.show()
        """
    )

    # there's your image
    data = result.results[0]
    assert data.png
    assert data.text
