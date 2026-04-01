from app import create_mcp


def main():
    mcp = create_mcp()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
